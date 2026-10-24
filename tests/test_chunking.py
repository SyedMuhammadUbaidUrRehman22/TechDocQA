import json
from pathlib import Path

from langchain_core.documents import Document
import pytest

from techdocqa.chunking import build_chunks, effective_config
from techdocqa.cli import main
from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.chunks import active_chunks, chunk_versions
from techdocqa.ingestion.pipeline import register_paths
from techdocqa.ingestion.processing import process_versions
from techdocqa.normalization import normalize_documents
from techdocqa.schemas import RegistrationMetadata
from techdocqa.settings import ChunkingSettings, ModelSettings


def normalized(text, **metadata):
    doc = normalize_documents([Document(page_content=text, metadata=metadata)])[0]
    doc.metadata.update(document_id='doc_test', version_id='ver_test', title='Technical source')
    return doc


def test_framework_coverage_overlap_ten_pairs_and_repeatability():
    doc = normalized('# Kafka\n' + 'Events persist durably. Consumers read by offset. ' * 300)
    settings = ChunkingSettings()
    runs = [build_chunks([doc], settings) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    chunks = runs[0]['chunks']
    assert len(chunks) > 10
    assert chunks[0]['start'] == 0 and chunks[-1]['end'] == len(doc.page_content)
    for left, right in zip(chunks, chunks[1:]):
        assert right['start'] <= left['end']
    for left, right in list(zip(chunks, chunks[1:]))[:10]:
        overlap = right['overlap_characters']
        assert 0 < overlap <= settings.overlap
        assert left['text'][-overlap:] == right['text'][:overlap]
    assert all(c['size'] == len(c['text']) <= settings.size and c['text'].strip() for c in chunks)
    assert all(c['text'] == doc.page_content[c['start']:c['end']] for c in chunks)
    assert all(c['section_path'] == ['Kafka'] and c['version_id'] == 'ver_test' for c in chunks)


@pytest.mark.parametrize('code', ['```python\n' + 'x = 1\n' * 50 + '```\n', '~~~sql\nSELECT 1;\n~~~\n'])
def test_fitting_code_stays_verbatim(code):
    doc = normalized('# Config\n' + 'Prose line. ' * 90 + '\n' + code + '\nTail prose.')
    chunks = build_chunks([doc], ChunkingSettings())['chunks']
    assert any(code.rstrip('\n') in c['text'] for c in chunks)
    assert not any(c['oversize_split'] for c in chunks)


def test_large_code_lines_and_single_oversized_line_are_bounded_and_flagged():
    code = '```sql\n' + ('SELECT id FROM events;\n' * 100) + ('x' * 1200) + '\n```'
    doc = normalized('# SQL\n' + code)
    chunks = build_chunks([doc], ChunkingSettings())['chunks']
    assert any(c['oversize_split'] for c in chunks)
    assert all(c['size'] <= 1000 for c in chunks)
    assert chunks[-1]['end'] == len(doc.page_content)


def test_occurrences_keep_identical_text_distinct_pages_and_sections():
    first = normalized('Repeated technical body. ' * 30, page=1)
    second = normalized(first.page_content, page=2)
    chunks = build_chunks([first, second], ChunkingSettings())['chunks']
    assert chunks[0]['text_hash'] == chunks[1]['text_hash']
    assert chunks[0]['chunk_id'] != chunks[1]['chunk_id']
    assert [c['page'] for c in chunks] == [1, 2]
    doc = normalized('# First\n' + first.page_content + '\n# Second\n' + first.page_content)
    chunks = build_chunks([doc], ChunkingSettings())['chunks']
    assert {tuple(c['section_path']) for c in chunks} == {('First',), ('Second',)}


def test_tiny_provenance_section_is_explicit_and_empty_chunks_are_discarded():
    doc = normalized('# Tiny\nShort.\n# Large\n' + 'word ' * 300)
    chunks = build_chunks([doc], ChunkingSettings())['chunks']
    assert chunks[0]['minimum_exception'] == 'provenance_or_size_boundary'
    assert chunks[0]['section_path'] == ['Tiny']
    assert all(c['text'].strip() for c in chunks)
    with pytest.raises(TechDocQAError, match='No usable chunks'):
        build_chunks([Document(page_content='  ', metadata={'version_id': 'v'})], ChunkingSettings())


def test_tokenizer_fallback_and_config_identity():
    first_id, first = effective_config(ChunkingSettings(unit='tokens'))
    assert first['effective_unit'] == 'characters'
    assert first['fallback_reason'] == 'provider_tokenizer_unavailable'
    assert first_id != effective_config(ChunkingSettings())[0]
    assert first_id != effective_config(ChunkingSettings(size=900, unit='tokens'))[0]


def test_verified_embedding_profile_bounds_unicode_and_preserves_requested_config():
    profile = ModelSettings(embedding_model='nomic-embed-text', embedding_context_window=2048,
        embedding_tokenizer='bert', embedding_model_digest='a' * 64, embedding_prefix='search_document: ')
    _, config = effective_config(ChunkingSettings(), profile)
    assert config['requested_size'] == 1000 and config['size'] == 507
    doc = normalized('😀' * 1500)
    result = build_chunks([doc], ChunkingSettings(), model=profile)
    assert result['config'] == config
    assert all(len(c['text'].encode('utf-8')) + 19 <= 2048 for c in result['chunks'])
    assert all(c['size'] <= 507 for c in result['chunks'])
    changed = profile.model_copy(update={'embedding_model_digest': 'b' * 64})
    assert effective_config(ChunkingSettings(), profile)[0] != effective_config(ChunkingSettings(), changed)[0]


def test_unverified_or_too_small_embedding_profile_fails_at_startup():
    with pytest.raises(TechDocQAError) as error:
        effective_config(ChunkingSettings(), ModelSettings(embedding_model='nomic-embed-text'))
    assert error.value.response.error.code == 'EMBEDDING_PROFILE_UNVERIFIED'
    profile = ModelSettings(embedding_model='nomic-embed-text', embedding_context_window=100,
        embedding_tokenizer='bert', embedding_model_digest='a' * 64)
    with pytest.raises(TechDocQAError) as error:
        effective_config(ChunkingSettings(), profile)
    assert error.value.response.error.code == 'INVALID_CONFIGURATION'


@pytest.fixture
def chunk_source(corpus, settings, registry):
    source = corpus / 'source.md'
    source.write_text('# Kafka\n' + 'Consumers read durable events. ' * 150, encoding='utf-8')
    result = register_paths([source], settings, registry, metadata=RegistrationMetadata(technology='Kafka'))
    candidate = result.outcomes[0].result
    assert process_versions([candidate.version_id], settings, registry).run.failed == 0
    return source, candidate.version_id


def test_persisted_repeat_config_switch_and_offline_reopen(chunk_source, settings, registry, monkeypatch):
    _, version = chunk_source
    first = chunk_versions([version], settings, registry)
    assert first.run.stage == 'chunking' and first.run.processed == 1 and first.run.failed == 0
    before = registry.get_version(version)
    old_chunks = active_chunks(version, settings, registry)
    assert before.status == 'chunked' and first.chunk_count == len(old_chunks)
    assert registry.get_run(first.run.run_id).run.stage == 'chunking'
    def forbidden(*args, **kwargs):
        raise AssertionError('Unchanged chunking must not launch a worker')
    import techdocqa.ingestion.chunks as pipeline
    worker = pipeline.run_processing_worker
    monkeypatch.setattr(pipeline, 'run_processing_worker', forbidden)
    repeat = chunk_versions([version], settings, registry)
    assert repeat.run.skipped == 1 and active_chunks(version, settings, registry) == old_chunks
    monkeypatch.setattr(pipeline, 'run_processing_worker', worker)
    settings.chunking.size = 700
    changed = chunk_versions([version], settings, registry)
    assert changed.run.processed == 1 and changed.run.failed == 0
    after = registry.get_version(version)
    assert after.chunking.chunking_config_id != before.chunking.chunking_config_id
    assert {c['chunking_config_id'] for c in active_chunks(version, settings, registry)} == {after.chunking.chunking_config_id}
    assert (Path(settings.data_directory) / before.chunking.snapshot_path).exists()
    from techdocqa.registry import Registry
    with Registry(registry.path) as reopened:
        assert active_chunks(version, settings, reopened) == active_chunks(version, settings, registry)
    assert process_versions([version], settings, registry).run.skipped == 1
    assert registry.get_version(version).status == 'chunked'


def test_failure_preserves_prior_chunks_and_corruption_fails_closed(chunk_source, settings, registry, monkeypatch):
    _, version = chunk_source
    assert chunk_versions([version], settings, registry).run.failed == 0
    before = registry.get_version(version)
    settings.chunking.size = 700
    import techdocqa.ingestion.chunks as pipeline
    def broken(*args, **kwargs):
        raise TechDocQAError('PARSE_TIMEOUT', 'Worker deadline exceeded.', stage='chunking')
    monkeypatch.setattr(pipeline, 'run_processing_worker', broken)
    assert chunk_versions([version], settings, registry).run.failed == 1
    assert registry.get_version(version).chunking == before.chunking
    assert active_chunks(version, settings, registry)
    path = Path(settings.data_directory) / before.chunking.snapshot_path
    path.write_bytes(b'corrupt')
    with pytest.raises(TechDocQAError) as error:
        active_chunks(version, settings, registry)
    assert error.value.response.error.code == 'SNAPSHOT_MISMATCH'


def test_superseded_and_duplicate_versions_cannot_expose_active_chunks(chunk_source, corpus, settings, registry):
    source, version = chunk_source
    assert chunk_versions([version], settings, registry).run.failed == 0
    duplicate = corpus / 'copy.md'
    duplicate.write_bytes(source.read_bytes())
    copied = register_paths([duplicate], settings, registry).outcomes[0].result.version_id
    process_versions([copied], settings, registry)
    assert chunk_versions([copied], settings, registry).run.failed == 1
    assert active_chunks(copied, settings, registry) == []
    source.write_text(source.read_text() + 'Changed source content.', encoding='utf-8')
    newer = register_paths([source], settings, registry).outcomes[0].result.version_id
    process_versions([newer], settings, registry)
    assert active_chunks(version, settings, registry) == []
    assert chunk_versions([version], settings, registry).run.failed == 1


def test_cli_chunk_config_status_history_and_sanitized_missing_version(chunk_source, settings, registry, monkeypatch, capsys):
    _, version = chunk_source
    monkeypatch.setattr('techdocqa.cli.load_settings', lambda *_: settings)
    assert main(['chunk', version]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['chunk_count'] > 0 and payload['run']['stage'] == 'chunking'
    assert main(['status', '--status', 'chunked']) == 0
    assert json.loads(capsys.readouterr().out)['documents'][0]['chunking']['chunk_count'] > 0
    assert main(['chunk', 'secret-path-or-argument']) == 1
    output = capsys.readouterr()
    assert 'secret-path-or-argument' not in output.out + output.err
    assert any(e['decision'] == 'CHUNKS_ACTIVATED' for e in registry.history(registry.get_version(version).document_id)['events'])


def test_pending_new_candidate_does_not_hide_active_version(chunk_source, settings, registry):
    source, version = chunk_source
    source.write_text(source.read_text() + 'A pending change.', encoding='utf-8')
    register_paths([source], settings, registry)
    result = chunk_versions([], settings, registry)
    assert result.run.processed == 1 and result.outcomes[0].result.version_id == version


def test_chunk_worker_timeout_records_chunking_stage(settings, monkeypatch):
    import subprocess
    from techdocqa.ingestion.processing import run_processing_worker
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('worker', 1)
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(TechDocQAError) as error:
        run_processing_worker({'chunking': {'size': 1000}}, settings)
    assert error.value.response.error.code == 'PARSE_TIMEOUT'
    assert error.value.response.error.stage == 'chunking'


def test_interrupted_chunk_run_recovers_without_replacing_prior_chunks(chunk_source, settings, registry):
    _, version = chunk_source
    chunk_versions([version], settings, registry)
    prior = registry.get_version(version).chunking
    run_id, attempts = registry.start_run(1, stage='chunking')
    registry.begin_chunking(version, attempts[0])
    assert chunk_versions([version], settings, registry).run.skipped == 1
    recovered = registry.get_run(run_id)
    assert recovered.run.failed == 1 and recovered.run.stage == 'chunking'
    assert recovered.outcomes[0].error.code == 'RUN_INTERRUPTED'
    assert recovered.outcomes[0].error.stage == 'chunking'
    assert registry.get_version(version).chunking == prior


def test_activation_rollback_preserves_prior_artifact(chunk_source, settings, registry, monkeypatch):
    _, version = chunk_source
    chunk_versions([version], settings, registry)
    prior = registry.get_version(version).chunking
    settings.chunking.size = 700
    original = registry.event
    def fail_activation(**kwargs):
        if kwargs.get('decision') == 'CHUNKS_ACTIVATED':
            raise TechDocQAError('REGISTRY_ERROR', 'Activation failed safely.', stage='registry')
        original(**kwargs)
    monkeypatch.setattr(registry, 'event', fail_activation)
    result = chunk_versions([version], settings, registry)
    assert result.run.failed == 1
    assert registry.get_version(version).chunking == prior
    assert active_chunks(version, settings, registry)


def test_unexpected_chunk_worker_failure_is_sanitized_and_stage_correct(tmp_path):
    import subprocess
    import sys
    marker = 'private-chunk-input'
    request = {'directory': str(tmp_path / marker), 'chunking': ChunkingSettings().model_dump()}
    result = subprocess.run([sys.executable, '-I', '-m', 'techdocqa.ingestion.processing_worker'],
        input=json.dumps(request).encode(), capture_output=True, check=False)
    payload = json.loads(result.stdout)
    assert payload['error']['code'] == 'PROCESSING_FAILED' and payload['error']['stage'] == 'chunking'
    assert marker.encode() not in result.stdout + result.stderr


def test_oversized_block_keeps_lines_that_fit_the_hard_limit_whole():
    first, second = 'a' * 900 + '\n', 'b' * 900 + '\n'
    doc = normalized('# Code\n```text\n' + first + second + '```')
    chunks = build_chunks([doc], ChunkingSettings())['chunks']
    assert any(first in chunk['text'] for chunk in chunks)
    assert any(second in chunk['text'] for chunk in chunks)
    assert all(chunk['size'] <= 1000 for chunk in chunks)
    block_start = doc.page_content.index('```')
    for chunk in chunks:
        if chunk['start'] > block_start:
            assert doc.page_content[chunk['start'] - 1] == '\n'


def test_failed_policy_upgrade_keeps_old_artifact_readable(chunk_source, settings, registry, monkeypatch):
    _, version = chunk_source
    chunk_versions([version], settings, registry)
    prior = active_chunks(version, settings, registry)
    monkeypatch.setattr('techdocqa.chunking.SEGMENTATION_POLICY', 'test-new-sentence-policy')
    def failure(*args, **kwargs):
        raise TechDocQAError('PARSE_TIMEOUT', 'Chunk generation deadline exceeded.', stage='chunking')
    monkeypatch.setattr('techdocqa.ingestion.chunks.run_processing_worker', failure)
    assert chunk_versions([version], settings, registry).run.failed == 1
    assert active_chunks(version, settings, registry) == prior
