"""FR-11, FR-12, FR-13, FR-21 and FR-02/FR-20 index slices, offline with a counting fake embedder."""

import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

import pytest

from techdocqa.cli import main
from techdocqa.enrichment.entities import Gazetteer, config_id
from techdocqa.errors import TechDocQAError
from techdocqa.indexing import embeddings
from techdocqa.indexing.lifecycle import delete_document, withdraw_document
from techdocqa.indexing.pipeline import entry_metadata, index_versions
from techdocqa.indexing.vector_store import VectorStore
from techdocqa.ingestion.chunks import active_chunks, chunk_versions
from techdocqa.ingestion.pipeline import register_paths
from techdocqa.ingestion.processing import process_versions
from techdocqa.registry import SCHEMA, Registry
from techdocqa.retrieval.lexical import LexicalIndex, tokenize
from techdocqa.retrieval.search import search
from techdocqa.schemas import RegistrationMetadata, SearchFilters, SearchRequest
from techdocqa.settings import ModelSettings

DIMENSION = 64
TOPICS = {
    'kafka.md': ('Kafka', 'Kafka brokers replicate partitions. The max.poll.interval.ms setting bounds consumer polling. '),
    'redis.md': ('Redis', 'Redis keeps keys in memory. The snake_case_setting and maxMemoryPolicy control eviction. '),
    'http.md': ('Web', 'Clients negotiate HTTP/2 with servers. The --flag-name option enables multiplexed streams. '),
    'cpp.md': ('Languages', 'Templates in C++ generate code at compile time. Compilers instantiate each use. '),
}


class CountingEmbeddings:
    """Deterministic word-hash vectors; a poison marker yields the configured bad vector."""

    def __init__(self):
        self.documents = 0
        self.requests = 0
        self.queries = 0
        self.poison = {}
        self.fail = False

    def vector(self, text):
        values = [0.0] * DIMENSION
        for word in re.findall(r'\w+', text.casefold()):
            if word not in {'search_document', 'search_query'}:
                values[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSION] += 1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def embed_documents(self, texts):
        self.requests += 1
        if self.fail:
            raise ConnectionError('secret provider detail')
        self.documents += len(texts)
        result = []
        for text in texts:
            bad = next((value for marker, value in self.poison.items() if marker in text), None)
            result.append(bad if bad is not None else self.vector(text))
        return result

    def embed_query(self, text):
        self.queries += 1
        if self.fail:
            raise ConnectionError('secret provider detail')
        return self.vector(text)


@pytest.fixture(autouse=True)
def inline_workers(monkeypatch):
    from techdocqa.ingestion import chunks, processing
    from techdocqa.ingestion.processing_worker import process
    monkeypatch.setattr(processing, 'run_processing_worker', lambda request, settings: process(request))
    monkeypatch.setattr(chunks, 'run_processing_worker', lambda request, settings: process(request))


@pytest.fixture
def embedder(monkeypatch):
    fake = CountingEmbeddings()
    monkeypatch.setattr(embeddings, 'build_embeddings', lambda settings: fake)
    return fake


@pytest.fixture
def model_settings(settings):
    settings.model = ModelSettings(embedding_model='nomic-embed-text:latest', embedding_tokenizer='bert',
        embedding_context_window=2048, embedding_model_digest='a' * 64, embedding_prefix='search_document: ',
        embedding_query_prefix='search_query: ', embedding_dimension=DIMENSION, embedding_normalization='l2', embedding_batch_size=4)
    return settings


def ingest(path, settings, registry, **metadata):
    result = register_paths([path], settings, registry, metadata=RegistrationMetadata(**metadata))
    candidate = result.outcomes[0].result
    processed = process_versions([candidate.version_id], settings, registry)
    assert processed.run.failed == 0
    resolved = processed.outcomes[0].result
    if resolved.duplicate_of:
        return resolved
    assert chunk_versions([resolved.version_id], settings, registry).run.failed == 0
    return resolved


@pytest.fixture
def indexed(corpus, model_settings, registry, embedder):
    versions = {}
    for name, (technology, sentence) in TOPICS.items():
        path = corpus / name
        path.write_text(f'# {technology} guide\n\n' + sentence * 12, encoding='utf-8')
        versions[name] = ingest(path, model_settings, registry, technology=technology)
    result = index_versions([], model_settings, registry)
    assert result.run.failed == 0
    return versions


def query(settings, registry, text, mode='bm25', top_k=5, **filters):
    return search(SearchRequest(query=text, mode=mode, top_k=top_k, filters=SearchFilters(**filters)), settings, registry)


def collection(settings):
    return VectorStore(settings.data_directory, embeddings.embedding_profile(settings.model)['collection'])


# Tokenizer and BM25

@pytest.mark.parametrize('token', ['max.poll.interval.ms', 'snake_case_setting', 'c++', 'http/2', '--flag-name', 'c#'])
def test_tokenizer_keeps_whole_technical_forms(token):
    assert token in tokenize(f'Use {token.upper() if token == "c++" else token}, then stop.')


def test_tokenizer_adds_a_plain_word_view():
    tokens = tokenize('maxMemoryPolicy max.poll.interval.ms snake_case')
    assert {'maxmemorypolicy', 'max', 'memory', 'policy', 'poll', 'interval', 'ms', 'snake', 'case'} <= set(tokens)


def test_bm25_score_matches_hand_computation_with_configured_parameters():
    chunks = [{'chunk_id': f'c{i}', 'text': text} for i, text in enumerate(['alpha beta', 'beta gamma delta', 'gamma', 'delta'])]
    k1, b = 1.5, 0.5
    (top, score, _), = LexicalIndex(chunks, k1, b).search('alpha', 1)
    idf = math.log(4 - 1 + 0.5) - math.log(1 + 0.5)
    average = (2 + 3 + 1 + 1) / 4
    assert top['chunk_id'] == 'c0'
    assert score == pytest.approx(idf * (k1 + 1) / (1 + k1 * (1 - b + b * 2 / average)))


def test_bm25_returns_only_chunks_sharing_a_token_and_breaks_ties_by_id():
    chunks = [{'chunk_id': cid, 'text': text} for cid, text in [('b', 'same words'), ('a', 'same words'), ('c', 'other text'), ('d', 'more here')]]
    index = LexicalIndex(chunks, 1.2, 0.75)
    assert [chunk['chunk_id'] for chunk, _, _ in index.search('same', 5)] == ['a', 'b']
    assert index.search('absent', 5) == []
    assert [chunk['chunk_id'] for chunk, _, _ in index.search('same', 5, lambda chunk: chunk['chunk_id'] == 'b')] == ['b']


def test_filter_does_not_change_a_lexical_score(indexed, model_settings, registry):
    unfiltered = {r.chunk_id: r.scores['bm25'] for r in query(model_settings, registry, 'memory keys', top_k=50).results}
    filtered = query(model_settings, registry, 'memory keys', top_k=50, technology='Redis').results
    assert filtered and all(unfiltered[r.chunk_id] == r.scores['bm25'] for r in filtered)


def test_cached_lexical_index_follows_eligibility_and_parameters(indexed, model_settings, registry, monkeypatch):
    import techdocqa.retrieval.search as module
    version = indexed['kafka.md']
    assert version.document_id in {r.document_id for r in query(model_settings, registry, 'Kafka brokers').results}
    first = module.lexical_index(model_settings, registry.eligible_versions())
    assert module.lexical_index(model_settings, registry.eligible_versions()) is first
    withdraw_document(version.document_id, 'Out', registry)
    assert version.document_id not in {r.document_id for r in query(model_settings, registry, 'Kafka brokers').results}
    assert module.lexical_index(model_settings, registry.eligible_versions()) is not first


@pytest.mark.parametrize('text, marker', [('max.poll.interval.ms', 'max.poll.interval.ms'), ('C++', 'C++'), ('HTTP/2', 'HTTP/2'), ('--flag-name', '--flag-name')])
def test_identifier_queries_find_their_exact_token_first(indexed, model_settings, registry, text, marker):
    results = query(model_settings, registry, text).results
    assert marker in results[0].text
    assert results[0].scores['bm25'] is not None and results[0].ranks == {'bm25': 1}


def test_bm25_needs_no_embedding_provider(indexed, model_settings, registry, embedder):
    embedder.fail = True
    before = embedder.queries
    assert query(model_settings, registry, 'Kafka brokers').results
    assert embedder.queries == before


def test_bm25_serves_chunked_versions_before_any_index_run(corpus, model_settings, registry, embedder):
    path = corpus / 'solo.md'
    path.write_text('# Solo\n\n' + 'Durable journals protect writes. ' * 20, encoding='utf-8')
    ingest(path, model_settings, registry)
    assert query(model_settings, registry, 'journals').results
    assert query(model_settings, registry, 'journals', mode='vector').results == []
    assert embedder.requests == 0


# Embeddings

def test_every_chunk_gets_one_valid_embedding_and_profile_is_recorded(indexed, model_settings, registry):
    versions = list(indexed.values())
    expected = sum(len(active_chunks(item.version_id, model_settings, registry)) for item in versions)
    rows = registry.execute("SELECT status,COUNT(*) FROM chunk_embeddings GROUP BY status").fetchall()
    assert [tuple(row) for row in rows] == [('embedded', expected)]
    assert all(registry.get_version(item.version_id).status == 'indexed' for item in versions)
    profile = dict(registry.execute('SELECT * FROM embedding_profiles').fetchone())
    assert profile['provider'] == 'ollama' and profile['dimension'] == DIMENSION
    assert profile['normalization'] == 'l2' and profile['metric'] == 'cosine'
    assert profile['embedding_model_id'] == f"ollama/nomic-embed-text:latest@{'a' * 64}"
    assert len(collection(model_settings).ids()) == expected


def test_prefixes_are_applied_to_documents_and_queries(corpus, model_settings, registry, monkeypatch):
    seen = []
    class Recording(CountingEmbeddings):
        def embed_documents(self, texts):
            seen.extend(texts)
            return super().embed_documents(texts)
        def embed_query(self, text):
            seen.append(text)
            return super().embed_query(text)
    monkeypatch.setattr(embeddings, 'build_embeddings', lambda settings: Recording())
    path = corpus / 'solo.md'
    path.write_text('# Solo\n\n' + 'Durable journals protect writes. ' * 20, encoding='utf-8')
    ingest(path, model_settings, registry)
    index_versions([], model_settings, registry)
    query(model_settings, registry, 'journals', mode='vector')
    assert seen[0].startswith('search_document: ') and seen[-1] == 'search_query: journals'


def test_rerun_on_unchanged_chunks_makes_no_call_and_keeps_counts(indexed, model_settings, registry, embedder):
    entries = len(collection(model_settings).ids())
    rows = registry.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0]
    embedder.requests = 0
    embedder.fail = True
    repeat = index_versions([], model_settings, registry)
    assert embedder.requests == 0 and repeat.embedding_requests == 0
    assert repeat.run.skipped == len(indexed) and repeat.run.processed == 0 and repeat.indexed_entries == 0
    assert len(collection(model_settings).ids()) == entries
    assert registry.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0] == rows


@pytest.mark.parametrize('bad, reason', [
    ([float('nan')] + [0.0] * (DIMENSION - 1), 'NON_FINITE_VALUE'),
    ([float('inf')] + [0.0] * (DIMENSION - 1), 'NON_FINITE_VALUE'),
    ([0.0] * DIMENSION, 'ZERO_NORM'),
    ([1.0] * 3, 'INVALID_DIMENSION'),
    ([2.0] + [0.0] * (DIMENSION - 1), 'NOT_NORMALIZED'),
])
def test_invalid_vector_is_rejected_marked_and_never_stored(corpus, model_settings, registry, embedder, bad, reason):
    path = corpus / 'mixed.md'
    path.write_text('# Mixed\n\n' + 'Ordinary durable prose follows here. ' * 40 + '\n\n# Poison\n\n' + 'poisonmarker text. ' * 20, encoding='utf-8')
    version = ingest(path, model_settings, registry).version_id
    chunks = active_chunks(version, model_settings, registry)
    poisoned = [chunk['chunk_id'] for chunk in chunks if 'poisonmarker' in chunk['text']]
    assert 0 < len(poisoned) < len(chunks)
    embedder.poison = {'poisonmarker': bad}
    result = index_versions([version], model_settings, registry)
    assert result.run.failed == 1 and result.failed_chunks == len(poisoned)
    assert result.outcomes[0].error.code == 'EMBEDDING_FAILED'
    rows = {row['chunk_id']: row for row in registry.execute('SELECT * FROM chunk_embeddings').fetchall()}
    assert all(rows[cid]['status'] == 'embedding_failed' and rows[cid]['reason'] == reason for cid in poisoned)
    keys = {row[0] for row in registry.execute('SELECT chunk_key FROM embeddings').fetchall()}
    assert not {rows[cid]['chunk_key'] for cid in poisoned} & keys
    assert collection(model_settings).ids() == set()
    assert registry.get_version(version).status == 'chunked'
    # A retry re-embeds only what failed.
    embedder.poison, embedder.documents = {}, 0
    retry = index_versions([version], model_settings, registry)
    assert retry.run.failed == 0 and embedder.documents == len(poisoned)
    assert registry.get_version(version).status == 'indexed'
    assert not registry.execute("SELECT 1 FROM chunk_embeddings WHERE status='embedding_failed'").fetchone()


def test_provider_failure_is_recorded_without_leaking_and_leaves_bm25(corpus, model_settings, registry, embedder):
    path = corpus / 'solo.md'
    path.write_text('# Solo\n\n' + 'Durable journals protect writes. ' * 20, encoding='utf-8')
    version = ingest(path, model_settings, registry).version_id
    embedder.fail = True
    result = index_versions([version], model_settings, registry)
    assert result.run.failed == 1 and result.outcomes[0].error.retryable
    assert 'secret' not in result.model_dump_json()
    assert registry.execute("SELECT reason FROM chunk_embeddings").fetchone()[0] == 'PROVIDER_ERROR'
    assert query(model_settings, registry, 'journals').results
    with pytest.raises(TechDocQAError) as error:
        embedder.fail = True
        # The vector path has no indexed version here, so force the query path through a provider call.
        embeddings.embed_query('journals', model_settings, embeddings.embedding_profile(model_settings.model), embedder)
    assert error.value.response.error.code == 'EMBEDDING_PROVIDER_UNAVAILABLE' and 'secret' not in error.value.response.error.message


def history_decisions(registry, document_id):
    return [event['decision'] for event in registry.history(document_id)['events']]


def test_model_switch_uses_separate_collection_reembeds_and_logs_model_changed(indexed, model_settings, registry, embedder):
    first = collection(model_settings)
    count = len(first.ids())
    version = indexed['kafka.md']
    assert 'EMBEDDINGS_CREATED' in history_decisions(registry, version.document_id)
    model_settings.model.embedding_model = 'nomic-embed-text:v2'
    stale = index_versions([], model_settings, registry)
    assert stale.run.failed == len(indexed) and stale.outcomes[0].error.code == 'STALE_CHUNKS'
    assert chunk_versions([], model_settings, registry).run.failed == 0
    embedder.documents = 0
    result = index_versions([], model_settings, registry)
    assert result.run.failed == 0 and embedder.documents > 0
    assert 'MODEL_CHANGED' in history_decisions(registry, version.document_id)
    second = collection(model_settings)
    assert second.store._collection.name != first.store._collection.name
    assert len(first.ids()) == count and len(second.ids()) == result.embedded_chunks
    assert registry.execute('SELECT COUNT(*) FROM embedding_profiles').fetchone()[0] == 2


def test_editing_a_document_logs_content_changed_and_removes_old_entries(indexed, corpus, model_settings, registry, embedder):
    old = indexed['kafka.md']
    old_ids = {chunk['chunk_id'] for chunk in active_chunks(old.version_id, model_settings, registry)}
    (corpus / 'kafka.md').write_text('# Kafka guide\n\n' + 'Replacement text about tiered storage. ' * 12, encoding='utf-8')
    new = ingest(corpus / 'kafka.md', model_settings, registry, technology='Kafka')
    assert new.version_id != old.version_id
    # Superseded chunks leave both searches before any index run.
    assert not {r.chunk_id for r in query(model_settings, registry, 'max.poll.interval.ms').results} & old_ids
    assert not {r.chunk_id for r in query(model_settings, registry, 'Kafka brokers', mode='vector', top_k=20).results} & old_ids
    result = index_versions([], model_settings, registry)
    assert result.removed_entries == len(old_ids) and not collection(model_settings).ids() & old_ids
    assert 'CONTENT_CHANGED' in history_decisions(registry, old.document_id)
    assert any('tiered storage' in r.text for r in query(model_settings, registry, 'tiered storage', mode='vector').results)


def test_repeated_text_keeps_separate_occurrences_on_one_stored_vector(corpus, model_settings, registry, embedder):
    (corpus / 'one.md').write_text('# One\n\n' + 'Shared boilerplate paragraph about durability guarantees. ' * 100, encoding='utf-8')
    version = ingest(corpus / 'one.md', model_settings, registry).version_id
    chunks = active_chunks(version, model_settings, registry)
    texts = [chunk['text_hash'] for chunk in chunks]
    assert len(set(texts)) < len(texts)
    result = index_versions([version], model_settings, registry)
    assert embedder.documents == len(set(texts)) and result.embedded_chunks == len(chunks)
    assert len(collection(model_settings).ids()) == len(chunks)
    assert registry.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0] == len(set(texts))


# Vector search

def test_score_is_documented_cosine_scale(indexed, model_settings, registry):
    store = collection(model_settings)
    profile = embeddings.embedding_profile(model_settings.model)
    probe = [1.0] + [0.0] * (DIMENSION - 1)
    version = indexed['kafka.md'].version_id
    found = store.search(probe, 1, {'version_id': version})
    vectors = registry.load_vectors([found[0][0].metadata['chunk_key']])
    stored = embeddings.decode_vector(next(iter(vectors.values())))
    assert found[0][1] == pytest.approx((stored[0] + 1) / 2, abs=1e-5)
    assert 0 <= found[0][1] <= 1 and profile['metric'] == 'cosine'


def test_sentence_query_finds_its_chunk_with_required_fields(indexed, model_settings, registry):
    results = query(model_settings, registry, 'Kafka brokers replicate partitions.', mode='vector', top_k=3).results
    assert 'Kafka brokers' in results[0].text
    top = results[0].model_dump()
    assert all(top[field] is not None for field in ('chunk_id', 'document_id', 'title', 'section_path', 'rank'))
    assert 0 <= top['scores']['vector'] <= 1 and top['ranks'] == {'vector': 1}


def test_metadata_read_back_matches_registry_and_chunks_resolve(indexed, model_settings, registry):
    store = collection(model_settings)
    stored = store.store.get(include=['metadatas'])
    for chunk_id, metadata in zip(stored['ids'], stored['metadatas'], strict=True):
        record = registry.get_version(metadata['version_id'])
        assert metadata['document_id'] == record.document_id and metadata['chunk_id'] == chunk_id
        chunk = next(item for item in active_chunks(record.version_id, model_settings, registry) if item['chunk_id'] == chunk_id)
        key = embeddings.chunk_key(chunk['text_hash'], chunk['chunking_config_id'], embeddings.embedding_profile(model_settings.model)['embedding_model_id'])
        assert metadata == entry_metadata(chunk, record, key)
        assert metadata['title'] == record.title and metadata['technology'] == record.technology
        assert 'category' not in metadata and record.category is None
        assert all(isinstance(value, (str, int, float, bool)) for value in metadata.values())
        assert registry.get_document(record.document_id).document_id == record.document_id


def test_indexing_twice_with_explicit_upsert_leaves_count_unchanged(indexed, model_settings, registry):
    store = collection(model_settings)
    before = store.store.get(limit=1, include=['documents', 'metadatas', 'embeddings'])
    count = len(store.ids())
    store.upsert([(before['ids'][0], before['documents'][0], before['metadatas'][0], list(map(float, before['embeddings'][0])))])
    assert len(store.ids()) == count


@pytest.mark.parametrize('mode', ['bm25', 'vector'])
def test_filters_apply_identically_in_both_modes(indexed, model_settings, registry, mode):
    only_redis = query(model_settings, registry, 'Redis keys memory Kafka', mode=mode, technology='redis').results
    assert only_redis and {r.document_id for r in only_redis} == {indexed['redis.md'].document_id}
    kafka = indexed['kafka.md'].document_id
    assert {r.document_id for r in query(model_settings, registry, 'keys', mode=mode, document_id=kafka).results} <= {kafka}
    assert query(model_settings, registry, 'keys', mode=mode, technology='Unknown').results == []
    assert query(model_settings, registry, 'keys', mode=mode, category='absent').results == []


@pytest.mark.parametrize('mode', ['bm25', 'vector'])
def test_entity_filter_uses_verified_registry_memberships(indexed, model_settings, registry, embedder, mode):
    # Settings built in code keep the default gazetteer path relative; only load_settings resolves it. Use the repository
    # gazetteer so the test does not depend on the working directory.
    model_settings.enrichment.gazetteer = str(Path(__file__).resolve().parents[1] / 'config' / 'gazetteer.toml')
    before = embedder.queries
    assert query(model_settings, registry, 'keys', mode=mode, entity='Redis').results == []
    assert embedder.queries == before
    version = indexed['redis.md'].version_id
    chunk = active_chunks(version, model_settings, registry)[0]['chunk_id']
    registry.execute('INSERT INTO verified_entities(chunk_id,version_id,entity) VALUES (?,?,?)', (chunk, version, 'redis'))
    # A membership with no enrichment identity behind it is not current, so it filters nothing.
    assert query(model_settings, registry, 'keys memory', mode=mode, entity='REDIS').results == []
    enrichment = model_settings.enrichment
    current = config_id(Gazetteer(enrichment.gazetteer), enrichment.entity_verification_threshold)
    seed_enrichment(registry, version, current)
    assert [r.chunk_id for r in query(model_settings, registry, 'keys memory', mode=mode, entity='REDIS').results] == [chunk]
    # Rows written under another entity configuration (an old gazetteer or threshold) are stale until enrich reruns.
    registry.execute('UPDATE enrichments SET entity_config_id=? WHERE version_id=?', ('ec_stale', version))
    assert query(model_settings, registry, 'keys memory', mode=mode, entity='REDIS').results == []


def seed_enrichment(registry, version_id, entity_config_id):
    chunking = registry.get_version(version_id).chunking
    registry.execute('''INSERT INTO enrichments(version_id,chunking_config_id,snapshot_hash,enrichment_config_id,entity_config_id,
                        keyphrase_config_id,classifier_config_id,entity_count,verified_count,keyphrase_status,
                        classification_status,updated_at) VALUES (?,?,?,'en_x',?,'kc_x','cc_x',1,1,'unavailable','not_configured','t')''',
                     (version_id, chunking.chunking_config_id, chunking.snapshot_hash, entity_config_id))


QUERIES = ['Kafka brokers', 'consumer polling', 'Redis memory', 'eviction policy', 'HTTP/2 streams',
           'multiplexed option', 'templates compile', 'compilers instantiate', 'partitions replicate', 'keys in memory']


def top_five(settings, registry):
    return [[(r.chunk_id, r.scores['vector']) for r in query(settings, registry, text, mode='vector').results] for text in QUERIES]


def test_reopen_and_rebuild_restore_identical_top_five_without_model_calls(indexed, model_settings, registry, embedder):
    before = top_five(model_settings, registry)
    assert all(before)
    with Registry(registry.path) as reopened:
        assert top_five(model_settings, reopened) == before
    collection(model_settings).reset()
    with pytest.raises(TechDocQAError) as error:
        query(model_settings, registry, 'Kafka brokers', mode='vector')
    assert error.value.response.error.code == 'VECTOR_INDEX_MISSING'
    embedder.requests, embedder.fail = 0, True
    rebuilt = index_versions([], model_settings, registry, rebuild=True)
    assert rebuilt.run.failed == 0 and embedder.requests == 0 and rebuilt.indexed_entries > 0
    embedder.fail = False
    assert top_five(model_settings, registry) == before
    with pytest.raises(TechDocQAError, match='rebuild'):
        index_versions(['ver_x'], model_settings, registry, rebuild=True)


def test_rerank_needs_a_configured_reranker(indexed, model_settings, registry):
    for request in (SearchRequest(query='x', mode='hybrid', rerank=True), SearchRequest(query='x', mode='bm25', rerank=True)):
        with pytest.raises(TechDocQAError) as error:
            search(request, model_settings, registry)
        assert error.value.response.error.code == 'RERANKER_NOT_CONFIGURED'


def test_retrieval_config_id_is_stable_and_reflects_configuration(indexed, model_settings, registry):
    first = query(model_settings, registry, 'keys').retrieval_config_id
    assert first.startswith('rc_') and first == query(model_settings, registry, 'other').retrieval_config_id
    model_settings.retrieval.bm25_k1 = 2.0
    assert query(model_settings, registry, 'keys').retrieval_config_id != first


def test_rechunked_version_waits_for_vector_index_but_stays_lexical(indexed, model_settings, registry):
    version = indexed['kafka.md']
    old = {chunk['chunk_id'] for chunk in active_chunks(version.version_id, model_settings, registry)}
    model_settings.chunking.size = 700
    assert chunk_versions([version.version_id], model_settings, registry).run.failed == 0
    assert registry.get_version(version.version_id).status == 'chunked'
    assert version.document_id not in {r.document_id for r in query(model_settings, registry, 'Kafka brokers', mode='vector', top_k=20).results}
    assert version.document_id in {r.document_id for r in query(model_settings, registry, 'Kafka brokers').results}
    result = index_versions([version.version_id], model_settings, registry)
    assert result.run.failed == 0 and not collection(model_settings).ids() & old


def test_bm25_fails_closed_on_a_corrupt_artifact(indexed, model_settings, registry):
    record = registry.get_version(indexed['kafka.md'].version_id)
    (Path(model_settings.data_directory) / record.chunking.snapshot_path).write_bytes(b'corrupt')
    with pytest.raises(TechDocQAError) as error:
        query(model_settings, registry, 'Kafka')
    assert error.value.response.error.code == 'SNAPSHOT_MISMATCH'


# Withdrawal and deletion

@pytest.mark.parametrize('mode', ['bm25', 'vector'])
def test_withdrawal_leaves_search_immediately_and_is_logged(indexed, model_settings, registry, embedder, mode):
    version = indexed['kafka.md']
    assert version.document_id in {r.document_id for r in query(model_settings, registry, 'Kafka brokers', mode=mode, top_k=20).results}
    result = withdraw_document(version.document_id, 'License under review', registry)
    assert result.status == 'withdrawn' and result.version_id == version.version_id
    assert version.document_id not in {r.document_id for r in query(model_settings, registry, 'Kafka brokers', mode=mode, top_k=20).results}
    assert query(model_settings, registry, 'Kafka brokers', mode=mode, document_id=version.document_id).results == []
    record = registry.get_version(version.version_id)
    assert record.status == 'withdrawn' and not record.is_active and active_chunks(version.version_id, model_settings, registry) == []
    event = registry.history(version.document_id)['events'][-1]
    assert event['decision'] == 'DOCUMENT_WITHDRAWN' and event['reason'] == 'License under review' and event['timestamp']
    # Data stays on disk.
    assert (Path(model_settings.data_directory) / record.chunking.snapshot_path).exists()
    with pytest.raises(TechDocQAError) as error:
        withdraw_document(version.document_id, 'again', registry)
    assert error.value.response.error.code == 'NO_ACTIVE_VERSION'


def test_index_run_removes_withdrawn_entries_and_reingest_reactivates_without_model_calls(indexed, corpus, model_settings, registry, embedder):
    version = indexed['kafka.md']
    count = len(collection(model_settings).ids())
    own = {chunk['chunk_id'] for chunk in active_chunks(version.version_id, model_settings, registry)}
    withdraw_document(version.document_id, 'Temporary', registry)
    assert index_versions([], model_settings, registry).removed_entries == len(own)
    assert not collection(model_settings).ids() & own
    repeat = register_paths([corpus / 'kafka.md'], model_settings, registry)
    assert repeat.run.processed == 1 and repeat.run.skipped == 0 and not repeat.outcomes[0].result.deduplicated
    record = registry.get_version(version.version_id)
    assert record.is_active and record.status == 'chunked'
    assert 'DOCUMENT_REACTIVATED' in history_decisions(registry, version.document_id)
    assert version.document_id in {r.document_id for r in query(model_settings, registry, 'Kafka brokers').results}
    embedder.requests = 0
    assert index_versions([], model_settings, registry).run.failed == 0 and embedder.requests == 0
    assert len(collection(model_settings).ids()) == count
    assert version.document_id in {r.document_id for r in query(model_settings, registry, 'Kafka brokers', mode='vector').results}


def test_reactivation_does_not_displace_a_newer_active_version(indexed, corpus, model_settings, registry):
    old = indexed['kafka.md']
    original = (corpus / 'kafka.md').read_bytes()
    withdraw_document(old.document_id, 'Superseding', registry)
    (corpus / 'kafka.md').write_text('# Kafka guide\n\n' + 'Newer durable material arrives here. ' * 12, encoding='utf-8')
    new = ingest(corpus / 'kafka.md', model_settings, registry)
    (corpus / 'kafka.md').write_bytes(original)
    register_paths([corpus / 'kafka.md'], model_settings, registry)
    assert registry.get_version(old.version_id).status == 'withdrawn' and registry.active_version(old.document_id) == new.version_id


def test_reprocessing_does_not_reactivate_withdrawn_content(indexed, model_settings, registry):
    version = indexed['kafka.md']
    withdraw_document(version.document_id, 'Stay out', registry)
    process_versions([version.version_id], model_settings, registry)
    assert registry.get_version(version.version_id).status == 'withdrawn'


def test_repeat_and_renamed_duplicate_add_no_chunks_or_index_entries(indexed, corpus, model_settings, registry, embedder):
    """AC-05.1 and AC-05.4 count portions: an exact re-ingestion and a renamed copy leave chunk and entry counts unchanged."""
    def totals():
        chunks = sum(len(active_chunks(record.version_id, model_settings, registry)) for record in registry.eligible_versions())
        return chunks, len(collection(model_settings).ids())
    before = totals()
    original = indexed['kafka.md']
    assert ingest(corpus / 'kafka.md', model_settings, registry, technology='Kafka').version_id == original.version_id
    assert 'DUPLICATE_SKIPPED' in history_decisions(registry, original.document_id)
    (corpus / 'renamed.md').write_bytes((corpus / 'kafka.md').read_bytes())
    copy = ingest(corpus / 'renamed.md', model_settings, registry)
    assert registry.get_version(copy.version_id).duplicate_of == original.document_id
    embedder.requests = 0
    assert index_versions([], model_settings, registry).run.failed == 0
    assert totals() == before and embedder.requests == 0


def test_withdrawing_an_original_promotes_its_duplicate(indexed, corpus, model_settings, registry):
    original = indexed['kafka.md']
    (corpus / 'copy.md').write_bytes((corpus / 'kafka.md').read_bytes())
    copy = ingest(corpus / 'copy.md', model_settings, registry)
    assert registry.get_version(copy.version_id).duplicate_of == original.document_id
    withdraw_document(original.document_id, 'Original retired', registry)
    assert registry.get_version(copy.version_id).duplicate_of is None
    assert 'DUPLICATE_PROMOTED' in history_decisions(registry, copy.document_id)


def counts(registry, version_ids):
    marks = ','.join('?' * len(version_ids))
    return registry.execute(f'SELECT COUNT(*) FROM chunk_embeddings WHERE version_id IN ({marks})', version_ids).fetchone()[0]


@pytest.mark.parametrize('withdraw_first', [False, True])
def test_delete_removes_every_trace_of_the_document(indexed, model_settings, registry, withdraw_first):
    version = indexed['kafka.md']
    data = Path(model_settings.data_directory)
    record = registry.get_version(version.version_id)
    own = {chunk['chunk_id'] for chunk in active_chunks(version.version_id, model_settings, registry)}
    files = [data / path for path in (record.chunking.snapshot_path, record.processing.normalized_path, record.processing.snapshot_path)]
    assert all(path.exists() for path in files)
    if withdraw_first:
        withdraw_document(version.document_id, 'First', registry)
    result = delete_document(version.document_id, 'Rights expired', model_settings, registry)
    assert result.status == 'deleted' and result.removed_entries == len(own) and result.removed_files >= 3 and not result.warnings
    with pytest.raises(TechDocQAError) as error:
        registry.get_document(version.document_id)
    assert error.value.response.error.code == 'NOT_FOUND'
    assert not collection(model_settings).ids() & own and counts(registry, [version.version_id]) == 0
    assert query(model_settings, registry, 'max.poll.interval.ms').results == [] or \
        version.document_id not in {r.document_id for r in query(model_settings, registry, 'max.poll.interval.ms').results}
    assert not any(path.exists() for path in files)
    assert not registry.execute('SELECT 1 FROM events WHERE document_id=? OR version_id=?', (version.document_id, version.version_id)).fetchone()
    event = registry.execute("SELECT * FROM events WHERE decision='DOCUMENT_DELETED'").fetchone()
    assert version.document_id in event['reason'] and 'Rights expired' in event['reason'] and event['timestamp']
    assert registry.execute('PRAGMA foreign_key_check').fetchall() == []
    # Other documents stay searchable, and their run history still reads.
    assert query(model_settings, registry, 'Redis memory').results
    assert registry.get_run(registry.execute('SELECT run_id FROM runs LIMIT 1').fetchone()[0])


def test_delete_keeps_files_and_vectors_another_source_still_uses(corpus, model_settings, registry, embedder):
    body = '# Shared\n\n' + 'Common durable text about replication. ' * 20
    (corpus / 'one.md').write_text(body, encoding='utf-8')
    (corpus / 'two.txt').write_text(body, encoding='utf-8')
    first = ingest(corpus / 'one.md', model_settings, registry)
    second_path = corpus / 'copy.md'
    second_path.write_text(body, encoding='utf-8')
    second = ingest(second_path, model_settings, registry)
    index_versions([], model_settings, registry)
    kept = registry.get_version(second.version_id).processing.normalized_path
    delete_document(first.document_id, 'Duplicate retired', model_settings, registry)
    survivor = registry.get_version(second.version_id)
    assert survivor.duplicate_of is None and (Path(model_settings.data_directory) / kept).exists()
    assert chunk_versions([second.version_id], model_settings, registry).run.failed == 0
    assert index_versions([], model_settings, registry).run.failed == 0
    assert query(model_settings, registry, 'replication', mode='vector').results


def test_delete_also_removes_replaced_chunk_artifacts(indexed, model_settings, registry):
    version = indexed['kafka.md']
    old = Path(model_settings.data_directory) / registry.get_version(version.version_id).chunking.snapshot_path
    model_settings.chunking.size = 700
    chunk_versions([version.version_id], model_settings, registry)
    assert old.exists()
    delete_document(version.document_id, 'Gone', model_settings, registry)
    assert not old.exists()


def test_failed_vector_delete_leaves_document_withdrawn_and_retryable(indexed, model_settings, registry, monkeypatch):
    version = indexed['kafka.md']
    def broken(self, ids):
        raise TechDocQAError('VECTOR_STORE_FAILED', 'Store failed.', stage='indexing', retryable=True)
    monkeypatch.setattr(VectorStore, 'delete', broken)
    with pytest.raises(TechDocQAError):
        delete_document(version.document_id, 'First try', model_settings, registry)
    assert registry.get_version(version.version_id).status == 'withdrawn'
    monkeypatch.undo()
    assert delete_document(version.document_id, 'Second try', model_settings, registry).status == 'deleted'


# Provider construction

class FakeListing:
    def __init__(self, digest):
        self.models = [type('Item', (), {'model': 'nomic-embed-text:latest', 'digest': digest})()]


def test_provider_preflight_detects_digest_change_and_outage(model_settings, monkeypatch):
    import ollama
    class Client:
        digest = 'b' * 64
        def __init__(self, **kwargs):
            pass
        def list(self):
            return FakeListing(self.digest)
    monkeypatch.setattr(ollama, 'Client', Client)
    with pytest.raises(TechDocQAError) as error:
        embeddings.build_embeddings(model_settings)
    assert error.value.response.error.code == 'EMBEDDING_MODEL_CHANGED'
    Client.digest = 'a' * 64
    assert embeddings.build_embeddings(model_settings).model == 'nomic-embed-text:latest'
    def down(self):
        raise ConnectionError('secret')
    monkeypatch.setattr(Client, 'list', down)
    with pytest.raises(TechDocQAError) as error:
        embeddings.build_embeddings(model_settings)
    assert error.value.response.error.code == 'EMBEDDING_PROVIDER_UNAVAILABLE' and error.value.response.error.retryable
    model_settings.model.provider = 'openai'
    with pytest.raises(TechDocQAError) as error:
        embeddings.build_embeddings(model_settings)
    assert error.value.response.error.code == 'PROVIDER_NOT_AVAILABLE'


def test_query_embedder_is_verified_once_per_process_and_again_after_any_failure(model_settings, monkeypatch):
    # Phase 11, P11-2: building the embedder verifies the pinned digest, so it is reused, not rebuilt per query.
    built = []
    def builder(settings):
        built.append(CountingEmbeddings())
        return built[-1]
    monkeypatch.setattr(embeddings, 'build_embeddings', builder)
    profile = embeddings.embedding_profile(model_settings.model)
    first = embeddings.embed_query('journals', model_settings, profile)
    for _ in range(3):
        assert embeddings.embed_query('journals', model_settings, profile) == first
    assert len(built) == 1 and built[0].queries == 4
    # A failed embedding drops the embedder, so the next query builds, and so verifies, a new one.
    built[0].fail = True
    with pytest.raises(TechDocQAError) as error:
        embeddings.embed_query('journals', model_settings, profile)
    assert error.value.response.error.code == 'EMBEDDING_PROVIDER_UNAVAILABLE'
    embeddings.embed_query('journals', model_settings, profile)
    assert len(built) == 2
    # Other model settings, or a replaced builder, also build a new one.
    model_settings.model.timeout_seconds += 1
    embeddings.embed_query('journals', model_settings, profile)
    assert len(built) == 3
    def changed(settings):
        raise TechDocQAError('EMBEDDING_MODEL_CHANGED', 'The installed embedding model does not match the pinned digest.', stage='embedding')
    monkeypatch.setattr(embeddings, 'build_embeddings', changed)
    with pytest.raises(TechDocQAError) as error:
        embeddings.embed_query('journals', model_settings, profile)
    assert error.value.response.error.code == 'EMBEDDING_MODEL_CHANGED'
    # An embedder passed in is used as given, and the index pipeline still builds its own once per run.
    passed = CountingEmbeddings()
    embeddings.embed_query('journals', model_settings, profile, passed)
    assert passed.queries == 1


def test_unselected_embedding_profile_refuses_vector_work(settings, registry):
    with pytest.raises(TechDocQAError) as error:
        query(settings, registry, 'keys', mode='vector')
    assert error.value.response.error.code == 'EMBEDDING_PROFILE_UNVERIFIED'


# Registry migration and CLI

def test_schema_version_one_registry_migrates_in_place(tmp_path, corpus, settings):
    path = tmp_path / 'old.sqlite3'
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA + 'PRAGMA application_id=1413763393; PRAGMA user_version=1;')
    connection.execute("INSERT INTO documents(document_id,source_key,source_path,filename,created_at) VALUES ('doc_1','k','p','f','t')")
    connection.commit()
    connection.close()
    with Registry(path) as registry:
        assert registry.execute('PRAGMA user_version').fetchone()[0] == 3
        assert registry.execute('SELECT document_id FROM documents').fetchone()[0] == 'doc_1'
        assert registry.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0] == 0
    with Registry(path) as again:
        assert again.execute('PRAGMA user_version').fetchone()[0] == 3


def test_cli_workflow_index_search_withdraw_delete(indexed, model_settings, registry, monkeypatch, capsys):
    monkeypatch.setattr('techdocqa.cli.load_settings', lambda *_: model_settings)
    capsys.readouterr()
    version = indexed['kafka.md']
    assert main(['index']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['run']['stage'] == 'indexing' and payload['run']['skipped'] == len(indexed)
    assert main(['status', '--status', 'indexed']) == 0
    assert len(json.loads(capsys.readouterr().out)['documents']) == len(indexed)
    assert main(['search', 'max.poll.interval.ms', '--mode', 'bm25', '--technology', 'Kafka']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['mode'] == 'bm25' and payload['degraded'] is False and payload['retrieval_config_id'].startswith('rc_')
    assert set(payload['results'][0]) >= {'rank', 'chunk_id', 'document_id', 'title', 'section_path', 'page', 'text', 'scores', 'ranks'}
    assert main(['search', '--mode', 'bm25', '--', '--flag-name']) == 0
    assert json.loads(capsys.readouterr().out)['results']
    assert main(['search', 'Kafka brokers', '--mode', 'hybrid']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['mode'] == 'hybrid' and payload['degraded'] is False and set(payload['results'][0]['relevances']) == {'bm25', 'vector'}
    assert main(['search', 'x' * 1001]) == 2
    assert json.loads(capsys.readouterr().err)['error']['code'] == 'INVALID_ARGUMENT'
    assert main(['search', 'Kafka', '--top-k', '0']) == 2
    capsys.readouterr()
    assert main(['withdraw', version.document_id]) == 2
    capsys.readouterr()
    assert main(['withdraw', version.document_id, '--reason', 'Review']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'withdrawn'
    assert main(['delete', version.document_id, '--reason', 'Done']) == 1
    assert json.loads(capsys.readouterr().err)['error']['code'] == 'CONFIRMATION_REQUIRED'
    assert registry.get_document(version.document_id)
    assert main(['delete', version.document_id, '--reason', 'Done', '--yes']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'deleted'
    assert main(['status', '--document-id', version.document_id]) == 1
    assert json.loads(capsys.readouterr().err)['error']['code'] == 'NOT_FOUND'


def test_help_lists_phase_five_commands(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    output = capsys.readouterr().out
    assert all(command in output for command in ('ingest', 'index', 'search', 'status', 'withdraw', 'delete'))


def test_secret_in_reason_is_masked(indexed, model_settings, registry):
    version = indexed['kafka.md']
    result = withdraw_document(version.document_id, 'See https://x.example/?api_key=SECRET123', registry)
    assert 'SECRET123' not in result.model_dump_json()
    assert 'SECRET123' not in json.dumps(registry.history(version.document_id)['events'])
