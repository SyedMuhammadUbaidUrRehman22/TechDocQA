import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-c", "from techdocqa.cli import main; raise SystemExit(main())", *arguments],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def test_config_check_does_not_claim_provider_readiness():
    result = run_cli("config-check")
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["provider_connection_checked"] is False
    assert output["model_selection_complete"] is False


def test_require_models_fails_with_standard_error():
    result = run_cli("config-check", "--require-models")
    assert result.returncode == 1
    assert json.loads(result.stderr)["error"]["code"] == "INVALID_CONFIGURATION"


def test_invalid_configuration_does_not_echo_sensitive_input(tmp_path):
    path = tmp_path / "invalid.toml"
    marker = "private-" + tmp_path.name
    path.write_text(f'[model]\napi_key = "{marker}"\n', encoding="utf-8")
    result = run_cli("config-check", "--config", str(path))
    assert result.returncode == 1
    assert marker not in result.stdout + result.stderr


@pytest.mark.parametrize("arguments", [
    [], ["unknown"], ["--bad"], ["config-check", "--unexpected"],
    ["config-check", "--config"], ["ingest"], ["status"],
    ["status", "--status", "invalid"], ["status", "--document-id"],
    ["status", "--document-id", "doc_a", "--run-id", "run_a"],
    ["--json", "config-check", "--prof", "private"],
])
def test_argument_failures_are_standard_json(arguments):
    result = run_cli(*arguments)
    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "INVALID_ARGUMENT" and error["stage"] == "arguments"
    assert "Traceback" not in result.stderr and "usage:" not in result.stderr


def test_sensitive_argument_values_never_appear_in_errors(tmp_path):
    marker = "private-" + tmp_path.name
    for arguments in ([marker], ["config-check", "--unexpected", marker],
                      ["status", "--status", marker], ["config-check", "--config", marker]):
        result = run_cli(*arguments)
        assert result.returncode != 0
        assert marker not in result.stdout + result.stderr
        assert json.loads(result.stderr)["error"]["code"] in {"INVALID_ARGUMENT", "INVALID_CONFIGURATION"}


def config_for(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    config = tmp_path / "config.toml"
    config.write_text('allowed_directories = ["corpus"]\ndata_directory = "runtime"\n', encoding="utf-8")
    return corpus, str(config)


def test_blank_directory_cli_configuration_is_safe(tmp_path):
    config = tmp_path / "bad.toml"
    config.write_text('allowed_directories = ["   "]\n', encoding="utf-8")
    result = run_cli("config-check", "--config", str(config), "--json")
    assert result.returncode == 1 and result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "INVALID_CONFIGURATION"
    assert str(config) not in result.stderr


def test_ingest_status_list_and_history_work_across_processes(tmp_path):
    corpus, config = config_for(tmp_path)
    source = corpus / "one.md"
    source.write_bytes(b"# Kafka\nDo not extract this text in Phase 2.")
    ingested = run_cli("ingest", str(source), "--config", config, "--technology", "Kafka", "--license", "Apache-2.0", "--json")
    assert ingested.returncode == 0 and not ingested.stderr
    result = json.loads(ingested.stdout)
    assert result["run"]["processed"] == 1 and result["run"]["stage"] == "registration"
    doc_id = result["outcomes"][0]["result"]["document_id"]
    for arguments in (["status", "--document-id", doc_id], ["history", doc_id],
                      ["status", "--run-id", result["run"]["run_id"]],
                      ["list"], ["status", "--status", "registered"]):
        response = run_cli(*arguments, "--config", config, "--json")
        assert response.returncode == 0 and response.stderr == ""
        assert doc_id in response.stdout
        json.loads(response.stdout)
    listing = json.loads(run_cli("list", "--config", config).stdout)["documents"]
    assert listing[0]["technology"] == "Kafka" and listing[0]["license"] == "Apache-2.0"
    assert listing[0]["content_hash"] is None and listing[0]["page_count"] is None
    duplicate = json.loads(run_cli("--json", "ingest", str(source), "--config", config).stdout)
    assert duplicate["run"]["skipped"] == 1
    assert duplicate["outcomes"][0]["result"]["version_id"] == result["outcomes"][0]["result"]["version_id"]


def test_mixed_batch_uses_exit_one_and_keeps_results_in_json_stdout(tmp_path):
    corpus, config = config_for(tmp_path)
    (corpus / "one.txt").write_bytes(b"valid")
    (corpus / "bad.exe").write_bytes(b"unsupported")
    result = run_cli("ingest", str(corpus), "--config", config, "--json")
    assert result.returncode == 1 and result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["run"]["processed"] == 1 and payload["run"]["failed"] == 1
    assert len(payload["outcomes"]) == 2


def test_unknown_identifiers_and_invalid_metadata_are_safe(tmp_path):
    corpus, config = config_for(tmp_path)
    marker = "private-" + tmp_path.name
    for args in (["status", "--document-id", marker], ["status", "--run-id", marker], ["history", marker]):
        result = run_cli(*args, "--config", config)
        assert result.returncode == 1 and result.stdout == ""
        assert json.loads(result.stderr)["error"]["code"] == "NOT_FOUND"
        assert marker not in result.stderr
    source = corpus / "one.txt"
    source.write_bytes(b"one")
    invalid = run_cli("ingest", str(source), "--source-url", marker, "--config", config)
    assert json.loads(invalid.stderr)["error"]["code"] == "INVALID_METADATA"
    assert marker not in invalid.stdout + invalid.stderr


def test_help_and_version_remain_successful():
    result = run_cli("--help")
    assert result.returncode == 0 and result.stderr == ""
    for command in ("config-check", "ingest", "status", "list", "history"):
        assert command in result.stdout
    assert run_cli("--version").returncode == 0
