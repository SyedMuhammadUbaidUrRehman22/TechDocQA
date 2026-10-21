import json
import os
import sqlite3
import subprocess
import sys

import pytest

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.pipeline import register_paths
from techdocqa.registry import Registry
from techdocqa.schemas import RegistrationMetadata


def test_unchanged_registration_reuses_ids_and_logs_each_attempt(corpus, settings, registry):
    source = corpus / "one.md"
    source.write_text("one", encoding="utf-8")
    first = register_paths([source], settings, registry).outcomes[0].result
    repeat = register_paths([source], settings, registry)
    assert repeat.outcomes[0].result.version_id == first.version_id
    assert repeat.outcomes[0].result.document_id == first.document_id
    assert repeat.outcomes[0].result.deduplicated
    assert (repeat.run.processed, repeat.run.skipped) == (0, 1)
    history = registry.history(first.document_id)
    assert len(history["registrations"]) == 1
    assert [item["decision"] for item in history["events"]] == ["REGISTERED", "DUPLICATE_SKIPPED"]


def test_changed_bytes_create_linked_candidate_and_failed_retry_reuses_it(corpus, settings, registry):
    source = corpus / "one.md"
    source.write_bytes(b"first")
    first = register_paths([source], settings, registry).outcomes[0].result
    source.write_bytes(b"changed")
    second = register_paths([source], settings, registry).outcomes[0].result
    assert second.document_id == first.document_id and second.version_id != first.version_id
    record = registry.get_document(first.document_id)
    assert record.previous_version_id == first.version_id
    registry.fail_registration(second.version_id)
    assert registry.get_document(first.document_id).status == "failed"
    history = registry.history(first.document_id)
    assert history["registrations"][0]["status"] == "registered"
    assert all(not item["is_active"] and item["content_hash"] is None for item in history["registrations"])
    retry = register_paths([source], settings, registry)
    assert retry.outcomes[0].result.version_id == second.version_id
    assert not retry.outcomes[0].result.deduplicated and retry.run.processed == 1
    assert len(registry.history(first.document_id)["registrations"]) == 2


def test_byte_change_that_might_normalize_away_remains_provisional(corpus, settings, registry):
    source = corpus / "one.txt"
    source.write_bytes(b"one")
    first = register_paths([source], settings, registry).outcomes[0].result
    source.write_bytes(b"one \n")
    second = register_paths([source], settings, registry).outcomes[0].result
    assert first.version_id != second.version_id
    assert not second.finalized and not second.is_active
    assert registry.get_document(first.document_id).content_hash is None


def test_identical_bytes_different_sources_keep_distinct_documents(corpus, settings, registry):
    first = corpus / "first.txt"
    second = corpus / "second.txt"
    first.write_bytes(b"same bytes")
    second.write_bytes(first.read_bytes())
    result = register_paths([first, second], settings, registry)
    one, two = [item.result for item in result.outcomes]
    assert one.document_id != two.document_id
    assert two.duplicate_of == one.document_id and not two.deduplicated


def test_same_filename_different_directory_requires_logical_name(corpus, settings, registry):
    first = corpus / "same.txt"
    second = corpus / "other/same.txt"
    second.parent.mkdir()
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    result = register_paths([first, second], settings, registry)
    assert result.run.processed == 1 and result.outcomes[1].error.code == "SOURCE_KEY_COLLISION"
    distinct = register_paths([second], settings, registry, logical_name="other")
    assert distinct.outcomes[0].result.document_id != result.outcomes[0].result.document_id
    assert len(registry.list_documents()) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive identity")
def test_windows_case_and_path_aliases_are_idempotent(corpus, settings, registry):
    source = corpus / "Mixed.txt"
    source.write_bytes(b"same")
    first = register_paths([source], settings, registry).outcomes[0].result
    second = register_paths([corpus / "MIXED.TXT"], settings, registry).outcomes[0].result
    assert first.version_id == second.version_id


def test_reopen_preserves_records_and_never_stores_document_contents(corpus, settings, registry):
    marker = "full-body-" + corpus.parent.name
    source = corpus / "one.txt"
    source.write_text(marker, encoding="utf-8")
    result = register_paths([source], settings, registry)
    identifier = result.outcomes[0].result.document_id
    with Registry(registry.path) as reopened:
        assert reopened.get_document(identifier) == registry.get_document(identifier)
        assert reopened.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert marker.encode() not in registry.path.read_bytes()


def test_sql_like_metadata_is_data_not_sql(corpus, settings, registry):
    source = corpus / "one.txt"
    source.write_bytes(b"one")
    title = "'); DROP TABLE documents; --"
    result = register_paths([source], settings, registry, metadata=RegistrationMetadata(title=title), logical_name=title)
    assert registry.get_document(result.outcomes[0].result.document_id).title == title
    assert len(registry.list_documents()) == 1


def test_failed_registration_transaction_rolls_back_and_can_retry(corpus, settings, registry, monkeypatch):
    source = corpus / "one.txt"
    source.write_bytes(b"one")
    original = registry.event
    def fail_success_event(**kwargs):
        if kwargs["decision"] == "REGISTERED":
            raise TechDocQAError("REGISTRY_ERROR", "Simulated transaction failure.", stage="registry")
        return original(**kwargs)
    monkeypatch.setattr(registry, "event", fail_success_event)
    failed = register_paths([source], settings, registry)
    assert failed.run.failed == 1 and registry.list_documents() == []
    assert registry.execute("SELECT COUNT(*) FROM registrations").fetchone()[0] == 0
    monkeypatch.setattr(registry, "event", original)
    assert register_paths([source], settings, registry).run.processed == 1


def test_unknown_schema_is_preserved(tmp_path):
    path = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sentinel(value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('preserved')")
    with pytest.raises(TechDocQAError) as caught:
        Registry(path)
    assert caught.value.response.error.code == "REGISTRY_SCHEMA_MISMATCH"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "preserved"


def test_newer_schema_is_not_overwritten(registry):
    registry.connection.execute("PRAGMA user_version=99")
    with pytest.raises(TechDocQAError) as caught:
        Registry(registry.path)
    assert caught.value.response.error.code == "REGISTRY_SCHEMA_MISMATCH"
    assert registry.connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_foreign_keys_and_transactions_reject_dangling_records(registry):
    with pytest.raises(TechDocQAError):
        with registry.transaction():
            registry.event(document_id="missing", decision="TEST", reason="test")
    assert registry.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert registry.connection.in_transaction is False


def test_writer_contention_has_safe_retryable_error(registry):
    with Registry(registry.path, timeout=0) as second:
        with registry.transaction():
            with pytest.raises(TechDocQAError) as caught:
                second.start_run(1)
            assert caught.value.response.error.code == "REGISTRY_BUSY"
            assert caught.value.response.error.retryable
        assert second.start_run(1)[0].startswith("run_")


def test_ingestion_lock_rejects_live_run_without_recovering_it(corpus, settings, registry):
    source = corpus / "one.txt"
    source.write_bytes(b"one")
    run_id, _ = registry.start_run(1)
    with registry.registration_lock():
        with Registry(registry.path) as second:
            with pytest.raises(TechDocQAError) as caught:
                register_paths([source], settings, second)
            assert caught.value.response.error.code == "REGISTRY_BUSY"
            assert second.get_run(run_id).run.status == "running"


def test_process_death_recovers_pending_attempt_and_preserves_committed_file(corpus, settings, registry):
    source = corpus / "one.txt"
    second = corpus / "two.txt"
    source.write_bytes(b"one")
    second.write_bytes(b"two")
    code = """
import os, sys
from pathlib import Path
from techdocqa.registry import Registry
from techdocqa.settings import Settings
from techdocqa.schemas import RegistrationMetadata
from techdocqa.ingestion.safety import validate_file
with Registry(Path(sys.argv[1])) as registry:
    with registry.registration_lock():
        run_id, attempts = registry.start_run(2)
        settings = Settings(allowed_directories=[sys.argv[2]])
        registry.register(validate_file(Path(sys.argv[3]), settings), RegistrationMetadata(), None, attempts[0])
        print(run_id, flush=True)
        os._exit(17)
"""
    crashed = subprocess.run([sys.executable, "-c", code, str(registry.path), str(corpus), str(source)], text=True, capture_output=True)
    assert crashed.returncode == 17, crashed.stderr
    old_run = crashed.stdout.strip()
    assert registry.get_run(old_run).run.status == "running"
    assert registry.get_run(old_run).run.processed == 1
    assert registry.get_run(old_run).outcomes[1].status == "pending"
    rerun = register_paths([source, second], settings, registry)
    recovered = registry.get_run(old_run)
    assert recovered.run.status == "completed_with_errors"
    assert recovered.run.processed == 1 and recovered.run.failed == 1
    assert recovered.outcomes[1].error.code == "RUN_INTERRUPTED"
    assert (rerun.run.processed, rerun.run.skipped) == (1, 1)
    assert len(registry.list_documents()) == 2
