"""FR-24 operations (Phase 12): JSON logs, manual retry and the `check` command. Model-free: no provider is called."""

import json
import os
from pathlib import Path

import pytest

from techdocqa import health, logs, providers
from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.pipeline import register_paths
from techdocqa.recovery import retry_run


def registered(corpus, settings, registry, name):
    source = corpus / name
    source.write_text(f"{name} text", encoding="utf-8")
    return register_paths([source], settings, registry).outcomes[0].result


def failed_run(registry, result, *, retryable, stage="normalization"):
    """A finished stage run whose one attempt failed on `result`'s version."""
    run_id, (attempt_id,) = registry.start_run(1, stage=stage)
    with registry.transaction():
        registry.execute("UPDATE attempts SET document_id=?,version_id=? WHERE attempt_id=?",
                         (result.document_id, result.version_id, attempt_id))
    registry.fail_attempt(attempt_id, TechDocQAError("TEST_FAILURE", "Test failure.", stage=stage, retryable=retryable).response.error)
    registry.finish_run(run_id)
    return run_id


# Logs never break the operation they record (bug 1)

def test_an_uncreatable_log_directory_turns_logging_off(settings):
    data = Path(settings.data_directory)
    data.mkdir(parents=True)
    (data / "logs").write_text("not a directory", encoding="utf-8")
    assert logs.configure(settings) is None
    logs.log_event("test", "EVENT")


def test_an_unwritable_log_file_is_skipped_silently(settings, registry, capsys):
    path = logs.configure(settings)
    path.mkdir()  # A directory where the file should be: opening it for append fails.
    run_id, attempts = registry.start_run(1, stage="normalization")
    registry.fail_attempt(attempts[0], TechDocQAError("TEST_FAILURE", "Test failure.", stage="normalization").response.error)
    registry.finish_run(run_id)
    assert registry.get_run(run_id).run.status == "failed"
    assert capsys.readouterr().err == ""


def test_log_lines_are_written_when_the_file_is_writable(settings, registry):
    path = logs.configure(settings)
    registry.start_run(0)
    logs.close()
    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["event"] == "RUN_STARTED" and set(logs.REQUIRED) <= set(entry)


# Retry (bugs 2 and 3, nit 4)

def test_retry_recovers_an_interrupted_run_and_retries_it(settings, registry):
    run_id, _ = registry.start_run(2, stage="indexing")  # Never finished, as after Ctrl-C or a crash.
    result = retry_run(None, settings, registry)
    assert result.retry_of == run_id and registry.get_run(run_id).run.status == "failed"
    assert [(item.code, item.failure, item.action, item.command) for item in result.items] == \
        [("RUN_INTERRUPTED", "retryable", "rerun_command", "index")] * 2
    assert result.remaining == 2


def test_a_deleted_documents_failure_is_resolved(corpus, settings, registry):
    document = registered(corpus, settings, registry, "gone.md")
    run_id = failed_run(registry, document, retryable=True)
    registry.delete_document(document.document_id, "test")
    result = retry_run(run_id, settings, registry)
    assert [(item.version_id, item.action) for item in result.items] == [(None, "resolved")]
    assert result.rerun is None and result.remaining == 0
    # The marker names no document.
    assert not registry.execute("SELECT 1 FROM events WHERE document_id IS NOT NULL OR version_id IS NOT NULL").fetchone()


def test_a_registration_failure_without_a_document_stays_outstanding(settings, registry):
    run_id, attempts = registry.start_run(1)
    registry.fail_attempt(attempts[0], TechDocQAError("TEST_FAILURE", "Test failure.", stage="registration", retryable=True).response.error)
    registry.finish_run(run_id)
    result = retry_run(run_id, settings, registry)
    assert [(item.action, item.command) for item in result.items] == [("rerun_command", "ingest")] and result.remaining == 1


def test_latest_outstanding_run_skips_a_newer_permanent_failure(corpus, settings, registry):
    retryable = failed_run(registry, registered(corpus, settings, registry, "a.md"), retryable=True)
    failed_run(registry, registered(corpus, settings, registry, "b.md"), retryable=False)
    assert registry.latest_outstanding_run() == retryable


# The `check` command (nits 5 to 8)

def test_model_names_are_matched_with_their_tag():
    assert providers.tagged("nomic-embed-text") == "nomic-embed-text:latest"
    assert providers.tagged("qwen3:8b") == "qwen3:8b"
    assert providers.tagged("localhost:5000/team/model") == "localhost:5000/team/model:latest"
    installed = {"nomic-embed-text:latest": "a" * 64}
    assert providers.installed_digest(installed, "nomic-embed-text") == "a" * 64
    health.model_present(installed, "nomic-embed-text", "a" * 64, "EMBEDDING", pinned=True)


@pytest.mark.parametrize("installed, name, digest, pinned, code", [
    (None, "m", None, False, "LLM_PROVIDER_UNAVAILABLE"),
    ({}, None, None, False, "LLM_MODEL_NOT_CONFIGURED"),
    ({}, "m", None, False, "LLM_MODEL_NOT_FOUND"),
    ({"m:latest": "a"}, "m", None, True, "LLM_MODEL_NOT_PINNED"),
    ({"m:latest": "a"}, "m", "b", False, "LLM_MODEL_CHANGED"),
])
def test_model_checks_apply_the_rules_used_before_a_model_runs(installed, name, digest, pinned, code):
    with pytest.raises(TechDocQAError) as error:
        health.model_present(installed, name, digest, "LLM", pinned=pinned)
    assert error.value.response.error.code == code


def test_an_unpinned_embedder_is_down_but_an_unpinned_chat_model_is_not(settings):
    settings.model.embedding_model, settings.model.embedding_model_digest = "nomic-embed-text", None
    settings.model.chat_model, settings.model.chat_model_digest = "qwen3", None
    installed = {"nomic-embed-text:latest": "a", "qwen3:latest": "b"}
    assert health.probe("embedding_provider", lambda: health.embedding_ready(settings, installed)).code == "EMBEDDING_MODEL_NOT_PINNED"
    assert health.probe("llm_provider", lambda: health.llm_ready(settings, installed)).status == "ok"


def test_a_hosted_chat_provider_is_not_called_or_reported_down(settings, monkeypatch):
    import importlib.util
    settings.model.provider, settings.model.chat_model = "openai", "chat-model"
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    check = health.probe("llm_provider", lambda: health.llm_ready(settings, None))
    assert (check.status, check.code) == ("not_probed", "LLM_PROVIDER_NOT_PROBED")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert health.probe("llm_provider", lambda: health.llm_ready(settings, None)).code == "LLM_CREDENTIALS_MISSING"
    # Embeddings are Ollama-only, so that check is truly down.
    assert health.probe("embedding_provider", lambda: health.embedding_ready(settings, None)).code == "EMBEDDING_PROVIDER_NOT_AVAILABLE"


def test_the_reranker_check_uses_the_loaders_file_rule(tmp_path):
    from techdocqa.retrieval import cross_encoder
    for name in cross_encoder.REQUIRED_FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(name.encode())
    pinned = {name: cross_encoder.sha256(tmp_path / name) for name in cross_encoder.REQUIRED_FILES}
    cross_encoder.verify_files(tmp_path, pinned)
    for broken in ({**pinned, cross_encoder.CONFIG_FILE: "0" * 64}, {cross_encoder.MODEL_FILE: pinned[cross_encoder.MODEL_FILE]}):
        with pytest.raises(TechDocQAError) as error:
            cross_encoder.verify_files(tmp_path, broken)
        assert error.value.response.error.code == "RERANKER_UNAVAILABLE"
