from pathlib import Path

import pytest
from pydantic import ValidationError

from techdocqa.settings import ChunkingSettings, ModelSettings, Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_default_config_records_selected_local_models_and_paths():
    settings = load_settings(ROOT / "config/default.toml")
    assert settings.framework == "langchain"
    assert settings.model.provider == "ollama"
    assert settings.model.chat_model == "qwen3:1.7b"
    assert settings.model.embedding_model == "nomic-embed-text:latest"
    assert settings.model.embedding_context_window == 2048 and settings.model.embedding_tokenizer == 'bert'
    assert Path(settings.allowed_directories[0]) == ROOT / "data/corpus"
    # P10-6: hybrid met the measured-benefit rule over vector, and the owner made it the default (2026-11-13).
    assert settings.retrieval.mode == "hybrid"
    # P10-5: the reranker is pinned by revision and file hashes, and stays off until FR-19 shows a benefit.
    reranker = settings.retrieval.reranker
    assert reranker.model == "cross-encoder/ms-marco-MiniLM-L6-v2" and len(reranker.revision) == 40
    assert set(reranker.files_sha256) == {"onnx/model.onnx", "tokenizer.json", "config.json"} and not settings.retrieval.rerank
    settings.require_models()
    with pytest.raises(ValueError, match="must be selected"):
        Settings().require_models()
    assert (settings.model.context_window, settings.model.chat_tokenizer, settings.model.chat_reasoning) == (8192, "byte-bpe", False)
    settings.require_chat_profile()
    with pytest.raises(ValueError, match="chat_tokenizer"):
        Settings().require_chat_profile()


def test_timeout_defaults_follow_the_provider():
    assert ModelSettings().timeout_seconds == 60
    assert ModelSettings(provider="openai").timeout_seconds == 30
    assert ModelSettings(provider="openai", timeout_seconds=45).timeout_seconds == 45


def test_output_and_template_reserve_must_fit_the_window():
    ModelSettings(context_window=1024, max_output_tokens=512, chat_template_reserve_tokens=96)
    with pytest.raises(ValidationError, match="room in context_window"):
        ModelSettings(context_window=600, max_output_tokens=512, chat_template_reserve_tokens=96)


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


@pytest.mark.parametrize("entry", ["", " ", "\t\n", "\x00"])
def test_rejects_blank_or_invalid_allowed_directory(entry):
    with pytest.raises(ValidationError):
        Settings(allowed_directories=[entry])


@pytest.mark.parametrize("entry", ["", "  ", "\x00"])
def test_rejects_blank_or_invalid_storage_directory(entry):
    with pytest.raises(ValidationError):
        Settings(data_directory=entry)


def test_missing_directories_are_not_created_and_paths_are_normalized(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('allowed_directories = [" ./missing ", " ./missing "]\ndata_directory = " ./runtime "\n', encoding="utf-8")
    settings = load_settings(path)
    assert settings.allowed_directories == [str(tmp_path / "missing")]
    assert settings.data_directory == str(tmp_path / "runtime")
    assert not (tmp_path / "missing").exists()
    assert not (tmp_path / "runtime").exists()


def test_file_cannot_be_configured_as_directory(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('allowed_directories = ["config.toml"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        load_settings(path)


def test_inaccessible_configuration_directory_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('allowed_directories = ["blocked"]\n', encoding="utf-8")
    original = Path.stat
    def deny_blocked(self, *args, **kwargs):
        if self.name == "blocked":
            raise PermissionError("sensitive path")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", deny_blocked)
    with pytest.raises(PermissionError):
        load_settings(path)
