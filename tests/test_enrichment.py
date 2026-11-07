"""Phase 9 storage and lifecycle (P9-8): schema v3 with a verified backup, per-document transactions, skips, stale rows,
withdrawal and deletion, the entity filter (AC-07.2, AC-07.3), FR-08 rows and both retrieval invariants."""

import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from techdocqa.cli import main
from techdocqa.enrichment import keyphrases, pipeline
from techdocqa.enrichment.pipeline import enrich_versions, show_enrichment
from techdocqa.errors import TechDocQAError
from techdocqa.indexing.lifecycle import delete_document, withdraw_document
from techdocqa.ingestion.chunks import active_chunks
from techdocqa.ingestion.processing import finalized_documents
from techdocqa.registry import ENRICHMENT_TABLES, SCHEMA, SCHEMA_V2, Registry, storage_error
from techdocqa.settings import CategorySpec, EnrichmentSettings

from test_generation import ask, chat, qa_settings, write_config  # noqa: F401
from test_indexing import embedder, indexed, ingest, inline_workers, model_settings, query  # noqa: F401

GAZETTEER = Path(__file__).resolve().parents[1] / "config" / "gazetteer.toml"
CATEGORIES = [
    CategorySpec(name="Distributed streaming", description="Kafka brokers replicate partitions and bound consumer polling."),
    CategorySpec(name="Caching", description="Redis keeps keys in memory and controls eviction."),
    CategorySpec(name="Web", description="Clients negotiate HTTP with servers over multiplexed streams."),
]


@pytest.fixture
def enrich_settings(model_settings):
    model_settings.enrichment = EnrichmentSettings(gazetteer=str(GAZETTEER), categories=CATEGORIES,
                                                   unclassified_threshold=0.45, calibration_run_id="test_calibration")
    return model_settings


@pytest.fixture
def enriched(indexed, enrich_settings, registry, embedder):
    result = enrich_versions([], enrich_settings, registry)
    assert result.run.failed == 0, result
    return indexed


def table_rows(registry, version_id):
    return {table: [tuple(row) for row in registry.execute(f"SELECT * FROM {table} WHERE version_id=? ORDER BY 1,2,3", (version_id,)).fetchall()]
            for table in ENRICHMENT_TABLES}


# Schema v3 migration and its backup

def old_registry(path, version=2):
    connection = sqlite3.connect(path)
    schema = SCHEMA + (SCHEMA_V2 if version == 2 else "")
    connection.executescript(schema + f"PRAGMA application_id=1413763393; PRAGMA user_version={version};")
    connection.execute("INSERT INTO documents(document_id,source_key,source_path,filename,created_at) VALUES ('doc_1','k','p','f','t')")
    connection.commit()
    connection.close()


@pytest.mark.parametrize("version", [1, 2])
def test_upgrade_takes_a_verified_backup_then_migrates_in_one_transaction(tmp_path, version):
    path = tmp_path / "old.sqlite3"
    old_registry(path, version)
    with Registry(path) as registry:
        assert registry.execute("PRAGMA user_version").fetchone()[0] == 3
        assert registry.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 0
        assert registry.backup_path == tmp_path / "old.sqlite3.pre-v3.bak"
    # Restoring the backup gives back the pre-upgrade registry exactly.
    restored = tmp_path / "restored.sqlite3"
    shutil.copy(tmp_path / "old.sqlite3.pre-v3.bak", restored)
    copy = sqlite3.connect(restored)
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert copy.execute("PRAGMA user_version").fetchone()[0] == version
    assert copy.execute("SELECT document_id FROM documents").fetchall() == [("doc_1",)]
    copy.close()
    with Registry(path) as again:
        assert again.backup_path is None and again.execute("PRAGMA user_version").fetchone()[0] == 3


def test_a_new_registry_needs_no_backup(tmp_path):
    with Registry(tmp_path / "new.sqlite3") as registry:
        assert registry.backup_path is None and registry.execute("PRAGMA user_version").fetchone()[0] == 3
    assert not list(tmp_path.glob("*.bak"))


def test_a_failed_backup_changes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "old.sqlite3"
    old_registry(path)
    real = sqlite3.connect
    def connect(target, *args, **kwargs):
        if str(target).endswith(".bak"):
            raise sqlite3.OperationalError("disk full")
        return real(target, *args, **kwargs)
    monkeypatch.setattr("techdocqa.registry.sqlite3.connect", connect)
    with pytest.raises(TechDocQAError) as error:
        Registry(path)
    assert error.value.response.error.code == "REGISTRY_BACKUP_FAILED"
    assert real(path).execute("PRAGMA user_version").fetchone()[0] == 2


def test_no_commit_can_land_between_the_backup_and_the_migration(tmp_path, monkeypatch):
    path = tmp_path / "old.sqlite3"
    old_registry(path)
    original = Registry.backup_before_upgrade
    blocked = []
    def racing(self, version):
        original(self, version)
        other = sqlite3.connect(path, timeout=0)
        try:
            other.execute("INSERT INTO documents(document_id,source_key,source_path,filename,created_at) VALUES ('doc_2','k2','p2','f','t')")
        except sqlite3.OperationalError as error:
            blocked.append(str(error))
        finally:
            other.close()
    monkeypatch.setattr(Registry, "backup_before_upgrade", racing)
    with Registry(path) as registry:
        assert registry.execute("PRAGMA user_version").fetchone()[0] == 3
        assert registry.execute("SELECT document_id FROM documents").fetchall() == [("doc_1",)]
    assert blocked and "locked" in blocked[0]
    copy = sqlite3.connect(tmp_path / "old.sqlite3.pre-v3.bak")
    assert copy.execute("SELECT document_id FROM documents").fetchall() == [("doc_1",)]
    copy.close()


def test_a_second_opener_waits_and_finds_the_registry_upgraded(tmp_path):
    path = tmp_path / "old.sqlite3"
    old_registry(path)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    with pytest.raises(TechDocQAError) as error:
        Registry(path, timeout=0)
    assert error.value.response.error.code == "REGISTRY_BUSY"
    # The blocked opener wrote no backup, so it cannot leave or delete one.
    assert not list(tmp_path.glob("*.bak"))
    holder.execute("ROLLBACK")
    holder.close()
    with Registry(path) as first:
        assert first.backup_path == tmp_path / "old.sqlite3.pre-v3.bak"
    with Registry(path) as second:
        assert second.backup_path is None
    assert [item.name for item in tmp_path.glob("*.bak")] == ["old.sqlite3.pre-v3.bak"]


def test_an_existing_backup_is_never_overwritten(tmp_path):
    path = tmp_path / "old.sqlite3"
    old_registry(path)
    (tmp_path / "old.sqlite3.pre-v3.bak").write_bytes(b"earlier backup")
    with Registry(path) as registry:
        assert registry.backup_path == tmp_path / "old.sqlite3.pre-v3.1.bak"
    assert (tmp_path / "old.sqlite3.pre-v3.bak").read_bytes() == b"earlier backup"


# Writes, skips and failures

def test_rerun_skips_unchanged_documents_and_keeps_rows(enriched, enrich_settings, registry, embedder):
    before = {name: table_rows(registry, version.version_id) for name, version in enriched.items()}
    calls = embedder.queries
    again = enrich_versions([], enrich_settings, registry)
    assert again.run.skipped == len(enriched) and again.run.processed == 0
    assert {name: table_rows(registry, version.version_id) for name, version in enriched.items()} == before
    assert embedder.queries == calls


def test_a_failure_mid_document_leaves_its_previous_rows(enriched, enrich_settings, registry, monkeypatch):
    version = enriched["kafka.md"].version_id
    before = table_rows(registry, version)
    enrich_settings.enrichment.keyphrases_per_document = 3
    original = Registry.execute
    def failing(self, sql, parameters=()):
        if sql.startswith("INSERT INTO keyphrases"):
            # As Registry.execute reports any SQLite failure.
            raise storage_error(sqlite3.OperationalError("simulated crash"))
        return original(self, sql, parameters)
    monkeypatch.setattr(Registry, "execute", failing)
    result = enrich_versions([version], enrich_settings, registry)
    monkeypatch.setattr(Registry, "execute", original)
    assert result.run.failed == 1
    assert table_rows(registry, version) == before


def test_a_second_enrich_while_one_runs_is_busy(enriched, enrich_settings, registry):
    with registry.registration_lock():
        with Registry(registry.path) as other:
            with pytest.raises(TechDocQAError) as error:
                enrich_versions([], enrich_settings, other)
    assert error.value.response.error.code == "REGISTRY_BUSY"


def test_a_configuration_change_recomputes(enriched, enrich_settings, registry):
    enrich_settings.enrichment.keyphrases_per_document = 3
    result = enrich_versions([], enrich_settings, registry)
    assert result.run.processed == len(enriched)
    assert all(len(registry.version_keyphrases(v.version_id).get("document", [])) <= 3 for v in enriched.values())


# FR-07 rows and the entity filter

def test_ac_07_2_every_entity_names_a_current_chunk_and_slices_back(enriched, enrich_settings, registry):
    # The C++ fixture names nothing the gazetteer or the patterns cover, so it rightly has no entities.
    assert {name for name, version in enriched.items() if registry.version_entities(version.version_id)} == {
        "kafka.md", "redis.md", "http.md"}
    for version in enriched.values():
        chunks = {chunk["chunk_id"]: chunk for chunk in active_chunks(version.version_id, enrich_settings, registry)}
        documents = finalized_documents(version.version_id, enrich_settings, registry)
        found = registry.version_entities(version.version_id)
        stored = registry.execute("SELECT DISTINCT document_id FROM entities WHERE version_id=?", (version.version_id,)).fetchall()
        assert [row[0] for row in stored] == ([version.document_id] if found else [])
        for entity in found:
            chunk = chunks[entity["chunk_id"]]
            assert chunk["text"][entity["chunk_start"]:entity["chunk_end"]] == entity["text"]
            page = documents[entity["document_index"]].page_content
            assert page[entity["document_start"]:entity["document_end"]] == entity["text"]
            assert entity["verified"] == (entity["confidence"] >= 0.5)


@pytest.mark.parametrize("mode", ["bm25", "vector"])
def test_ac_07_3_entity_filter_returns_only_chunks_with_that_verified_entity(enriched, enrich_settings, registry, mode):
    verified = {row[0] for row in registry.execute("SELECT chunk_id FROM entities WHERE entity_key='redis' AND verified=1").fetchall()}
    results = query(enrich_settings, registry, "keys memory", mode=mode, entity="Redis").results
    assert results and {item.chunk_id for item in results} <= verified
    # An alias resolves to its canonical name: the Kafka document's user technology gives "Kafka" its context.
    kafka = query(enrich_settings, registry, "brokers", mode=mode, entity="kafka").results
    assert kafka and {item.document_id for item in kafka} == {enriched["kafka.md"].document_id}


def test_unverified_mentions_are_stored_but_never_filter(corpus, enrich_settings, registry, embedder):
    path = corpus / "novel.md"
    path.write_text("# Notes\n\n" + "Kafka wrote letters about his trials and travels. " * 20, encoding="utf-8")
    version = ingest(path, enrich_settings, registry)
    assert enrich_versions([version.version_id], enrich_settings, registry).run.failed == 0
    rows = registry.version_entities(version.version_id)
    assert rows and all(row["rule_id"] == "gazetteer-ambiguous" and not row["verified"] for row in rows if row["text"] == "Kafka")
    assert query(enrich_settings, registry, "letters", entity="Apache Kafka").results == []


def test_withdrawal_and_deletion_leave_no_stale_entity_or_category_match(enriched, enrich_settings, registry):
    redis = enriched["redis.md"]
    assert query(enrich_settings, registry, "keys", entity="Redis").results
    withdraw_document(redis.document_id, "test", registry)
    assert query(enrich_settings, registry, "keys", entity="Redis").results == []
    assert query(enrich_settings, registry, "keys", category="Caching").results == []
    delete_document(redis.document_id, "test", enrich_settings, registry)
    assert all(not rows for rows in table_rows(registry, redis.version_id).values())


def test_a_changed_document_is_invisible_to_filters_until_enriched_again(enriched, enrich_settings, registry, corpus):
    path = corpus / "redis.md"
    path.write_text("# Redis guide\n\n" + "Redis keeps hot keys in memory with an eviction policy. " * 12, encoding="utf-8")
    new = ingest(path, enrich_settings, registry, technology="Redis")
    assert new.version_id != enriched["redis.md"].version_id
    assert query(enrich_settings, registry, "keys", entity="Redis").results == []
    assert query(enrich_settings, registry, "keys", category="Caching").results == []
    assert show_enrichment(new.document_id, enrich_settings, registry)["status"] == "not_enriched"
    assert enrich_versions([new.version_id], enrich_settings, registry).run.failed == 0
    assert {item.version_id for item in query(enrich_settings, registry, "keys", entity="Redis").results} == {new.version_id}


# FR-08 rows

def test_ac_08_1_documents_store_ranked_keyphrases(enriched, enrich_settings, registry):
    pytest.importorskip("rake_nltk")
    for version in enriched.values():
        phrases = registry.version_keyphrases(version.version_id)["document"]
        assert 1 <= len(phrases) <= 10 and [p["rank"] for p in phrases] == list(range(1, len(phrases) + 1))
        assert [p["score"] for p in phrases] == sorted((p["score"] for p in phrases), reverse=True)


def test_per_chunk_keyphrases_when_enabled(indexed, enrich_settings, registry):
    pytest.importorskip("rake_nltk")
    enrich_settings.enrichment.keyphrases_per_chunk = True
    assert enrich_versions([], enrich_settings, registry).run.failed == 0
    version = indexed["kafka.md"].version_id
    chunk_ids = {chunk["chunk_id"] for chunk in active_chunks(version, enrich_settings, registry)}
    assert set(registry.version_keyphrases(version)) - {"document"} <= chunk_ids


def test_without_the_nlp_extra_keyphrases_are_reported_unavailable(indexed, enrich_settings, registry, monkeypatch):
    monkeypatch.setattr(keyphrases, "rake_version", lambda: None)
    result = enrich_versions([], enrich_settings, registry)
    assert result.run.failed == 0 and "KEYPHRASES_UNAVAILABLE" in result.warnings and result.keyphrases == 0
    assert registry.enrichment_state(indexed["kafka.md"].version_id)["keyphrase_status"] == "unavailable"


# Invariant 1: existing behavior is unchanged

@pytest.mark.parametrize("mode", ["bm25", "vector"])
def test_unfiltered_search_is_identical_before_and_after_enrich(indexed, enrich_settings, registry, embedder, mode):
    texts = ["Kafka brokers replicate partitions", "keys in memory", "HTTP/2 streams", "compile time templates"]
    before = [query(enrich_settings, registry, text, mode=mode).model_dump() for text in texts]
    assert enrich_versions([], enrich_settings, registry).run.failed == 0
    assert [query(enrich_settings, registry, text, mode=mode).model_dump() for text in texts] == before


def test_the_qa_prompt_does_not_read_enrichment(indexed, qa_settings, registry, chat, embedder):
    qa_settings.enrichment = EnrichmentSettings(gazetteer=str(GAZETTEER), categories=CATEGORIES,
                                                unclassified_threshold=0.45, calibration_run_id="test_calibration")
    first = ask(qa_settings, registry)
    assert enrich_versions([], qa_settings, registry).run.failed == 0
    second = ask(qa_settings, registry)
    assert [str(message.content) for message in chat.prompts[0]] == [str(message.content) for message in chat.prompts[1]]
    assert first.answer == second.answer and first.retrieval_config_id == second.retrieval_config_id


# CLI

def cli_config(tmp_path, settings) -> str:
    path = Path(write_config(tmp_path, settings))
    lines = [f"gazetteer = '{GAZETTEER.as_posix()}'", "unclassified_threshold = 0.45", 'calibration_run_id = "test_calibration"']
    for category in CATEGORIES:
        lines += ["[[enrichment.categories]]", f'name = "{category.name}"', f'description = "{category.description}"']
    path.write_text(path.read_text(encoding="utf-8") + "[enrichment]\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_cli_enrich_and_show(indexed, enrich_settings, registry, embedder, tmp_path, capsys):
    config = cli_config(tmp_path, enrich_settings)
    assert main(["enrich", "--config", config]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["run"]["stage"] == "enrichment" and result["run"]["processed"] == len(indexed) and result["entities"] > 0
    document = indexed["redis.md"].document_id
    assert main(["enrichment", document, "--config", config]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["status"] == "current" and shown["entities"] and shown["categories"]["effective"][0]["source"] == "embedding"
    chunk = shown["entities"][0]["chunk_id"]
    assert main(["enrichment", document, "--chunk-id", chunk, "--config", config]) == 0
    assert {row["chunk_id"] for row in json.loads(capsys.readouterr().out)["entities"]} == {chunk}
    assert main(["enrichment", document, "--chunk-id", "chk_missing", "--config", config]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "NOT_FOUND"
