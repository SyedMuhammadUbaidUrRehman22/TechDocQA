"""Validated nonsecret configuration; loading never calls a model provider."""

from pathlib import Path
from typing import Literal
import os
import tomllib

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelSettings(StrictModel):
    provider: Literal["ollama", "openai"] = "ollama"
    chat_model: str | None = Field(default=None, min_length=1, pattern=r"\S")
    embedding_model: str | None = Field(default=None, min_length=1, pattern=r"\S")
    context_window: int | None = Field(default=None, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=0.2)
    timeout_seconds: int = Field(default=60, gt=0)


class IngestionSettings(StrictModel):
    max_file_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=500, gt=0)
    parse_timeout_seconds: int = Field(default=60, gt=0)
    min_text_characters: int = Field(default=100, gt=0)


class ChunkingSettings(StrictModel):
    size: int = Field(default=1000, gt=0)
    overlap: int = Field(default=150, ge=0)
    minimum: int = Field(default=100, gt=0)
    unit: Literal["characters", "tokens"] = "characters"

    @model_validator(mode="after")
    def check_bounds(self) -> "ChunkingSettings":
        if self.overlap >= self.size or self.minimum > self.size:
            raise ValueError("overlap must be below size; minimum cannot exceed size")
        return self


class RetrievalSettings(StrictModel):
    mode: Literal["bm25", "vector", "hybrid"] = "vector"
    candidate_depth: int = Field(default=20, gt=0)
    top_k: int = Field(default=5, gt=0)
    bm25_k1: float = Field(default=1.2, gt=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    rrf_k: int = Field(default=60, gt=0)
    rerank: bool = False
    rerank_max_candidates: int = Field(default=20, gt=0)

    @model_validator(mode="after")
    def check_depth(self) -> "RetrievalSettings":
        if self.top_k > self.candidate_depth:
            raise ValueError("top_k cannot exceed candidate_depth")
        return self


class AnsweringSettings(StrictModel):
    max_question_characters: int = Field(default=1000, ge=1, le=1000)
    strict_citations: bool = True


class Settings(StrictModel):
    framework: Literal["langchain"] = "langchain"
    allowed_directories: list[str] = Field(default_factory=lambda: ["../data/corpus"], min_length=1)
    data_directory: str = Field(default="../data", min_length=1)
    model: ModelSettings = Field(default_factory=ModelSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    answering: AnsweringSettings = Field(default_factory=AnsweringSettings)

    def require_models(self) -> None:
        """Check selection only; provider availability is a later integration gate."""
        if not all((self.model.chat_model, self.model.embedding_model, self.model.context_window)):
            raise ValueError("chat_model, embedding_model and context_window must be selected")


def load_settings(path: Path, profile: Path | None = None) -> Settings:
    """Load base TOML, optional section overlay, then allowlisted environment values.

    Paths resolve relative to the base file, independent of working directory.
    Credentials are deliberately absent from these models and snapshots.
    """
    with path.open("rb") as handle:
        values = tomllib.load(handle)
    if profile is not None:
        with profile.open("rb") as handle:
            overlay = tomllib.load(handle)
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(values.get(key), dict):
                values[key] = {**values[key], **value}
            else:
                values[key] = value
    for variable, field in (
        ("TECHDOCQA_CHAT_MODEL", "chat_model"),
        ("TECHDOCQA_EMBEDDING_MODEL", "embedding_model"),
    ):
        if variable in os.environ:
            model_values = values.setdefault("model", {})
            if not isinstance(model_values, dict):
                raise ValueError("model configuration must be a table")
            model_values[field] = os.environ[variable]
    settings = Settings.model_validate(values)
    base = path.resolve().parent
    settings.allowed_directories = [str((base / item).resolve()) for item in settings.allowed_directories]
    settings.data_directory = str((base / settings.data_directory).resolve())
    return settings
