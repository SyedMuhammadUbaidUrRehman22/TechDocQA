from pathlib import Path

import pytest
from pydantic import ValidationError

from techdocqa.settings import ChunkingSettings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_default_config_keeps_model_unselected_and_paths_local():
    settings = load_settings(ROOT / "config/default.toml")
    assert settings.framework == "langchain"
    assert settings.model.provider == "ollama"
    assert settings.model.chat_model is None
    assert Path(settings.allowed_directories[0]) == ROOT / "data/corpus"
    with pytest.raises(ValueError, match="must be selected"):
        settings.require_models()


def test_profile_and_environment_precedence(tmp_path, monkeypatch):
    base = tmp_path / "base.toml"
    base.write_text('[model]\nprovider = "ollama"\nchat_model = "base"\n', encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text('[model]\nchat_model = "profile"\ncontext_window = 4096\n', encoding="utf-8")
    monkeypatch.setenv("TECHDOCQA_CHAT_MODEL", "environment")
    monkeypatch.setenv("TECHDOCQA_EMBEDDING_MODEL", "embedding")
    settings = load_settings(base, profile)
    assert settings.model.chat_model == "environment"
    assert settings.model.provider == "ollama"
    assert settings.model.context_window == 4096
    settings.require_models()


@pytest.mark.parametrize("values", [{"overlap": 1000}, {"minimum": 1001}, {"size": 0}])
def test_rejects_invalid_chunk_bounds(values):
    with pytest.raises(ValidationError):
        ChunkingSettings(**values)


def test_unknown_keys_and_credentials_are_rejected(tmp_path):
    path = tmp_path / "invalid.toml"
    path.write_text('[model]\napi_key = "test-value"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)
