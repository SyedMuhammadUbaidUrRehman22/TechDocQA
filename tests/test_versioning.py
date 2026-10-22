import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from techdocqa.cli import main
from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.pipeline import register_paths
from techdocqa.ingestion import processing
from techdocqa.ingestion.processing import finalized_documents, process_versions
from techdocqa.registry import Registry
from techdocqa.schemas import RegistrationMetadata

TEXT = "consumer.group and max.poll.interval.ms control Kafka polling. " * 3


@pytest.fixture
def fast_worker(monkeypatch):
    from techdocqa.ingestion.processing_worker import process
    monkeypatch.setattr(processing, "run_processing_worker", lambda request, settings: process(request))


def register(source, settings, registry, data=TEXT.encode(), **kwargs):
    source.write_bytes(data)
    batch = register_paths([source], settings, registry, **kwargs)
    assert batch.run.failed == 0
    return batch.outcomes[0].result


def finalized_count(registry, document_id=None):
    return registry.execute("SELECT COUNT(*) FROM registrations WHERE finalized=1 AND (? IS NULL OR document_id=?)",
                            (document_id, document_id)).fetchone()[0]


def test_finalize_local_markdown_title_citations_and_immutable_content(corpus, settings, registry):
    source = corpus / "technical.md"
    raw = ("# Kafka Basics\n## Setup\n" + TEXT + "\n```python\nif dag_id:\n    print('consumer.group')\n```\n").encode()
    candidate = register(source, settings, registry, raw, metadata=RegistrationMetadata(technology="Kafka", version_label="4.3"))
    result = process_versions([candidate.version_id], settings, registry)
    assert result.run.status == "completed" and result.run.stage == "normalization" and result.run.processed == 1
    record = registry.get_document(candidate.document_id)
    assert record.finalized and record.is_active and record.status == "normalized"
    assert record.title == "Kafka Basics" and record.raw_hash == hashlib.sha256(raw).hexdigest()
    assert record.content_hash != record.raw_hash and record.processing.normalized_hash == record.content_hash
    docs = finalized_documents(candidate.version_id, settings, registry)
    assert docs[0].metadata["document_id"] == record.document_id and docs[0].metadata["version_id"] == record.version_id
    assert docs[0].metadata["version_label"] == "4.3" and docs[0].metadata["headings"][1]["section_path"] == ["Kafka Basics", "Setup"]
    assert "    print('consumer.group')" in docs[0].page_content
    assert TEXT.encode() not in registry.path.read_bytes() and str(source) not in record.model_dump_json()
    source.unlink()
    assert process_versions([candidate.version_id], settings, registry).run.skipped == 1


def test_exact_reingestion_and_metadata_changes_preserve_ids_and_first_metadata(corpus, settings, registry, fast_worker):
    source = corpus / "one.txt"
    first = register(source, settings, registry, metadata=RegistrationMetadata(title="Original", license="Synthetic"))
    process_versions([first.version_id], settings, registry)
    second = register_paths([source], settings, registry, metadata=RegistrationMetadata(title="Changed")).outcomes[0].result
    assert second.version_id == first.version_id and second.finalized and second.deduplicated
    repeat = process_versions([second.version_id], settings, registry)
    assert repeat.run.skipped == 1 and repeat.outcomes[0].result.version_id == first.version_id
    assert registry.get_document(first.document_id).title == "Original"
    assert finalized_count(registry) == 1


def test_changed_bytes_same_normalized_text_resolve_without_extra_finalized_version(corpus, settings, registry, fast_worker):
    source = corpus / "one.txt"
    first = register(source, settings, registry, (TEXT.rstrip() + "\n").encode())
    process_versions([first.version_id], settings, registry)
    second = register(source, settings, registry, (TEXT.rstrip().replace(" and ", "  and\t") + " \r\n").encode())
    result = process_versions([second.version_id], settings, registry)
    assert second.version_id != first.version_id
    assert result.outcomes[0].result.version_id == first.version_id and result.run.skipped == 1
    candidate = registry.get_version(second.version_id)
    assert not candidate.finalized and not candidate.is_active and candidate.content_hash is None
    assert candidate.processing.resolved_version_id == first.version_id
    assert candidate.processing.normalized_hash == registry.get_version(first.version_id).content_hash
    assert finalized_count(registry) == 1 and len(registry.history(first.document_id)["registrations"]) == 2
    assert register_paths([source], settings, registry).run.skipped == 1
    assert process_versions([second.version_id], settings, registry).run.skipped == 1


def test_changed_text_supersedes_atomically_and_old_bytes_do_not_restore(corpus, settings, registry, fast_worker):
    source = corpus / "one.txt"
    first = register(source, settings, registry)
    process_versions([first.version_id], settings, registry)
    second = register(source, settings, registry, (TEXT + "Changed content.").encode())
    assert registry.get_version(first.version_id).is_active
    process_versions([second.version_id], settings, registry)
    assert registry.get_version(first.version_id).status == "superseded"
    assert registry.get_version(second.version_id).is_active
    assert finalized_count(registry) == 2
    register(source, settings, registry)
    result = process_versions([first.version_id], settings, registry)
    assert result.run.skipped == 1 and not result.outcomes[0].result.is_active
    assert registry.get_version(second.version_id).is_active


def test_different_sources_identical_normalized_text_keep_identity_and_duplicate_link(corpus, settings, registry, fast_worker):
    one = register(corpus / "one.txt", settings, registry, TEXT.rstrip().encode())
    two = register(corpus / "two.txt", settings, registry, (TEXT.rstrip() + "\r\n ").encode())
    result = process_versions([one.version_id, two.version_id], settings, registry)
    assert result.run.processed == 2 and finalized_count(registry) == 2
    assert one.document_id != two.document_id
    a, b = registry.get_version(one.version_id), registry.get_version(two.version_id)
    assert a.content_hash == b.content_hash and a.raw_hash != b.raw_hash
    assert b.duplicate_of == a.document_id and a.is_active and b.is_active


@pytest.mark.parametrize("bad,code,status", [(b"   \r\n", "NO_TEXT_EXTRACTED", "extraction_failed"),
    ((TEXT + "\ufffd").encode(), "INVALID_EXTRACTED_CONTENT", "failed")])
def test_failed_candidate_does_not_replace_valid_version(bad, code, status, corpus, settings, registry, fast_worker):
    source = corpus / "one.txt"
    good = register(source, settings, registry)
    process_versions([good.version_id], settings, registry)
    bad_candidate = register(source, settings, registry, bad)
    result = process_versions([bad_candidate.version_id], settings, registry)
    assert result.run.failed == 1 and result.outcomes[0].error.code == code
    assert result.outcomes[0].error.document_id == good.document_id
    assert registry.get_version(bad_candidate.version_id).status == status
    assert registry.get_version(good.version_id).is_active and finalized_count(registry) == 1


def test_failed_finalization_rolls_back_supersession_and_retries(corpus, settings, registry, fast_worker, monkeypatch):
    source = corpus / "one.txt"
    first = register(source, settings, registry)
    process_versions([first.version_id], settings, registry)
    second = register(source, settings, registry, (TEXT + "New text").encode())
    original = registry.event
    def fail(**kwargs):
        if kwargs["decision"] == "VERSION_FINALIZED":
            raise TechDocQAError("REGISTRY_ERROR", "Synthetic rollback.", stage="registry")
        return original(**kwargs)
    monkeypatch.setattr(registry, "event", fail)
    failed = process_versions([second.version_id], settings, registry)
    assert failed.run.failed == 1 and registry.get_version(first.version_id).is_active
    assert not registry.get_version(second.version_id).finalized and finalized_count(registry) == 1
    monkeypatch.setattr(registry, "event", original)
    assert process_versions([second.version_id], settings, registry).run.processed == 1
    assert registry.get_version(second.version_id).is_active and not registry.get_version(first.version_id).is_active


def test_registered_mutable_bytes_cannot_be_silently_processed(corpus, settings, registry, fast_worker):
    source = corpus / "one.txt"
    candidate = register(source, settings, registry)
    source.write_bytes(b"Changed after registration")
    failed = process_versions([candidate.version_id], settings, registry)
    assert failed.outcomes[0].error.code == "SOURCE_CHANGED" and finalized_count(registry) == 0


def test_stale_candidate_rejected_and_mixed_batch_isolated(corpus, settings, registry, fast_worker):
    source = corpus / "one.txt"
    old = register(source, settings, registry)
    current = register(source, settings, registry, (TEXT + "Current").encode())
    result = process_versions([old.version_id, "missing", current.version_id], settings, registry)
    assert result.run.processed == 1 and result.run.failed == 2
    assert [item.error.code for item in result.outcomes[:2]] == ["STALE_CANDIDATE", "NOT_FOUND"]
    assert finalized_count(registry) == 1


def test_interrupted_processing_process_death_is_recovered(corpus, settings, registry, fast_worker):
    candidate = register(corpus / "one.txt", settings, registry)
    script = """
import os, sys
from pathlib import Path
from techdocqa.registry import Registry
with Registry(Path(sys.argv[1])) as registry:
    with registry.registration_lock():
        run, attempts = registry.start_run(1, stage='normalization')
        registry.begin_processing(sys.argv[2], attempts[0])
        print(run, flush=True)
        os._exit(17)
"""
    crashed = subprocess.run([sys.executable, "-c", script, str(registry.path), candidate.version_id], capture_output=True, text=True)
    assert crashed.returncode == 17, crashed.stderr
    run_id = crashed.stdout.strip()
    assert registry.get_version(candidate.version_id).status == "extracting"
    assert process_versions([candidate.version_id], settings, registry).run.processed == 1
    recovered = registry.get_run(run_id)
    assert recovered.run.failed == 1 and recovered.outcomes[0].error.code == "RUN_INTERRUPTED"
    assert recovered.run.stage == "normalization" and finalized_count(registry) == 1


def test_concurrent_runner_and_sql_contention_do_not_mutate_candidates(corpus, settings, registry, fast_worker):
    candidate = register(corpus / "one.txt", settings, registry)
    with Registry(registry.path, timeout=0) as other:
        with registry.registration_lock():
            with pytest.raises(TechDocQAError) as caught:
                process_versions([candidate.version_id], settings, other)
            assert caught.value.response.error.code == "REGISTRY_BUSY"
        with registry.transaction():
            with pytest.raises(TechDocQAError) as caught:
                other.start_run(1, stage="normalization")
            assert caught.value.response.error.code == "REGISTRY_BUSY"
    assert finalized_count(registry) == 0
    assert process_versions([candidate.version_id], settings, registry).run.processed == 1


def test_two_processes_contend_and_only_one_finalization_wins(corpus, settings, registry, fast_worker):
    candidate = register(corpus / "one.txt", settings, registry)
    script = """
import sys
from pathlib import Path
from techdocqa.registry import Registry
from techdocqa.settings import Settings
from techdocqa.ingestion.processing import process_versions
from techdocqa.errors import TechDocQAError
try:
    with Registry(Path(sys.argv[1])) as registry:
        process_versions([sys.argv[2]], Settings(data_directory=sys.argv[3]), registry)
except TechDocQAError as error:
    print(error.response.error.code)
"""
    with registry.registration_lock():
        contender = subprocess.run([sys.executable, "-c", script, str(registry.path), candidate.version_id,
                                   settings.data_directory], capture_output=True, text=True)
    assert contender.returncode == 0 and contender.stdout.strip() == "REGISTRY_BUSY", contender.stderr
    assert process_versions([candidate.version_id], settings, registry).run.processed == 1
    assert registry.execute("SELECT COUNT(*) FROM registrations WHERE is_active=1").fetchone()[0] == 1


def test_interruption_after_finalization_keeps_committed_outcome(corpus, settings, registry, fast_worker):
    candidate = register(corpus / "one.txt", settings, registry)
    with registry.registration_lock():
        run_id, attempts = registry.start_run(1, stage="normalization")
        registry.begin_processing(candidate.version_id, attempts[0])
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=settings.data_directory) as working:
            info = processing.prepare_candidate(registry.get_version(candidate.version_id), settings, registry, Path(working))
            registry.finalize(candidate.version_id, info, attempts[0])
        # Simulate a process stopping after commit but before finish_run.
    result = process_versions([candidate.version_id], settings, registry)
    assert result.run.skipped == 1 and finalized_count(registry) == 1
    assert registry.get_run(run_id).run.status == "completed" and registry.get_run(run_id).run.processed == 1


def test_failed_local_normalization_reuses_captured_raw_snapshot_after_source_disappears(corpus, settings, registry, fast_worker, monkeypatch):
    source = corpus / "one.txt"
    candidate = register(source, settings, registry)
    original = processing.run_processing_worker
    def fail(*args):
        raise TechDocQAError("PROCESSING_FAILED", "Synthetic failure.", stage="normalization")
    monkeypatch.setattr(processing, "run_processing_worker", fail)
    assert process_versions([candidate.version_id], settings, registry).run.failed == 1
    source.unlink()
    monkeypatch.setattr(processing, "run_processing_worker", original)
    assert process_versions([candidate.version_id], settings, registry).run.processed == 1


def test_finalization_rechecks_current_candidate_inside_transaction(corpus, settings, registry, fast_worker):
    candidate = register(corpus / "one.txt", settings, registry)
    with registry.registration_lock():
        run_id, attempts = registry.start_run(1, stage="normalization")
        registry.begin_processing(candidate.version_id, attempts[0])
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=settings.data_directory) as working:
            info = processing.prepare_candidate(registry.get_version(candidate.version_id), settings, registry, Path(working))
        # Simulate a caller bypassing the orchestration lock; finalization still checks SQL state.
        registry.execute("UPDATE documents SET current_version_id=NULL WHERE document_id=?", (candidate.document_id,))
        with pytest.raises(TechDocQAError) as caught:
            registry.finalize(candidate.version_id, info, attempts[0])
        assert caught.value.response.error.code == "STALE_CANDIDATE" and finalized_count(registry) == 0
        registry.fail_attempt(attempts[0], caught.value.response.error)
        registry.finish_run(run_id)
        registry.execute("UPDATE documents SET current_version_id=? WHERE document_id=?", (candidate.version_id, candidate.document_id))


def test_processing_never_constructs_model_providers(corpus, settings, registry, monkeypatch, fast_worker):
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    def denied(*args, **kwargs):
        raise AssertionError("No model/provider construction is allowed")
    monkeypatch.setattr(ChatOllama, "__init__", denied)
    monkeypatch.setattr(OllamaEmbeddings, "__init__", denied)
    candidate = register(corpus / "one.txt", settings, registry)
    assert process_versions([candidate.version_id], settings, registry).run.processed == 1


def test_snapshot_read_rejects_escaped_paths(settings, tmp_path):
    with pytest.raises(TechDocQAError) as caught:
        processing.read_snapshot(Path(settings.data_directory).resolve(), "../outside.txt", "0" * 64, 100)
    assert caught.value.response.error.code == "UNSAFE_STORAGE"


def test_tampered_finalized_snapshot_fails_without_mutating_active_version(corpus, settings, registry, fast_worker):
    candidate = register(corpus / "one.txt", settings, registry)
    process_versions([candidate.version_id], settings, registry)
    info = registry.get_version(candidate.version_id).processing
    (Path(settings.data_directory) / info.normalized_path).write_bytes(b"tampered")
    result = process_versions([candidate.version_id], settings, registry)
    assert result.run.failed == 1 and result.outcomes[0].error.code == "SNAPSHOT_MISMATCH"
    assert registry.get_version(candidate.version_id).is_active
    with pytest.raises(TechDocQAError):
        finalized_documents(candidate.version_id, settings, registry)


def test_worker_timeout_and_invalid_output_are_structured(settings, tmp_path, monkeypatch):
    original = subprocess.run
    def sleeping(command, **kwargs):
        return original([sys.executable, "-I", "-c", "import time; time.sleep(30)"], **kwargs)
    monkeypatch.setattr(processing.subprocess, "run", sleeping)
    settings.ingestion.parse_timeout_seconds = 1
    with pytest.raises(TechDocQAError) as caught:
        processing.run_processing_worker({"directory": str(tmp_path)}, settings)
    assert caught.value.response.error.code == "PARSE_TIMEOUT"
    monkeypatch.setattr(processing.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, b"[]"))
    with pytest.raises(TechDocQAError) as caught:
        processing.run_processing_worker({}, settings)
    assert caught.value.response.error.code == "PROCESSING_WORKER_FAILED"


def test_phase3a_registry_rows_read_without_schema_change(corpus, settings, registry, fast_worker):
    candidate = register(corpus / "one.txt", settings, registry)
    values = json.loads(registry.execute("SELECT metadata_json FROM registrations").fetchone()[0])
    values.pop("title_explicit")
    registry.execute("UPDATE registrations SET metadata_json=?", (json.dumps(values),))
    before = [tuple(row) for row in registry.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()]
    with Registry(registry.path) as reopened:
        assert reopened.get_document(candidate.document_id).processing is None
        assert process_versions([candidate.version_id], settings, reopened).run.processed == 1
    assert registry.execute("PRAGMA user_version").fetchone()[0] == 1
    assert before == [tuple(row) for row in registry.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()]


def test_process_cli_preserves_json_contract_and_exit_codes(tmp_path, capsys, fast_worker):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    config = tmp_path / "config.toml"
    config.write_text('allowed_directories=["corpus"]\ndata_directory="runtime"\n', encoding="utf-8")
    source = corpus / "one.txt"
    source.write_text(TEXT, encoding="utf-8")
    assert main(["ingest", str(source), "--config", str(config)]) == 0
    candidate = json.loads(capsys.readouterr().out)["outcomes"][0]["result"]
    assert candidate["status"] == "registered" and not candidate["finalized"]
    assert main(["process", "--config", str(config), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["run"]["stage"] == "normalization" and result["outcomes"][0]["result"]["finalized"]
    assert main(["process", "unknown", "--config", str(config)]) == 1
    assert json.loads(capsys.readouterr().out)["outcomes"][0]["error"]["code"] == "NOT_FOUND"
