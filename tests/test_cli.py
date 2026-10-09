import json
from pathlib import Path
import subprocess
import sys

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
