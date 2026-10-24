"""Validated nonsecret configuration; loading never calls a model provider."""

from pathlib import Path
from typing import Literal
import os
import stat
import tomllib

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelSettings(StrictModel):
    provider: Literal["ollama", "openai"] = "ollama"
    chat_model: str | None = Field(default=None, min_length=1, pattern=r"\S")
    embedding_model: str | None = Field(default=None, min_length=1, pattern=r"\S")
    embedding_context_window: int | None = Field(default=None, gt=0)
    embedding_tokenizer: Literal["bert"] | None = None
    embedding_model_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    embedding_prefix: str = ""
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


class OnlineSource(StrictModel):
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    technology: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    source_type: Literal["online_documentation"] = "online_documentation"
    entry_url: str
    scopes: list[str] = Field(min_length=1, max_length=20)
    pages: list[str] = Field(min_length=1, max_length=20)
    enabled: bool = False
    usage_policy_url: str | None = None
    usage_status: Literal["unverified", "reviewed"] = "unverified"

    @model_validator(mode="after")
    def validate_urls(self):
        from techdocqa.ingestion.urls import canonical_url, in_scope
        self.entry_url = canonical_url(self.entry_url)
        self.scopes = list(dict.fromkeys(canonical_url(item) for item in self.scopes))
        self.pages = list(dict.fromkeys(canonical_url(item) for item in self.pages))
        if not all(in_scope(item, self.scopes) for item in [self.entry_url, *self.pages]):
            raise ValueError("catalog page is outside its declared scope")
        if self.usage_policy_url is not None:
            self.usage_policy_url = canonical_url(self.usage_policy_url)
        return self


class OnlineSettings(StrictModel):
    sources: list[OnlineSource] = Field(default_factory=list, max_length=30)
    max_pages_per_run: int = Field(default=10, ge=1, le=20)
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    read_timeout_seconds: int = Field(default=10, ge=1, le=30)
    retries: int = Field(default=2, ge=0, le=3)
    max_redirects: int = Field(default=3, ge=0, le=5)
    request_interval_seconds: int = Field(default=1, ge=1, le=10)

    @model_validator(mode="after")
    def unique_sources(self):
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise ValueError("duplicate source IDs")
        pages = [url for source in self.sources for url in {source.entry_url, *source.pages}]
        if len(set(pages)) != len(pages):
            raise ValueError("a page must belong to one source")
        return self


class Settings(StrictModel):
    framework: Literal["langchain"] = "langchain"
    allowed_directories: list[str] = Field(default_factory=lambda: ["../data/corpus"], min_length=1)
    data_directory: str = Field(default="../data", min_length=1)
    model: ModelSettings = Field(default_factory=ModelSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    answering: AnsweringSettings = Field(default_factory=AnsweringSettings)
    online: OnlineSettings = Field(default_factory=OnlineSettings)

    @field_validator("allowed_directories")
    @classmethod
    def validate_directories(cls, values: list[str]) -> list[str]:
        if any(not item.strip() or "\x00" in item for item in values):
            raise ValueError("allowed directories must contain nonblank paths")
        return list(dict.fromkeys(item.strip() for item in values))

    @field_validator("data_directory")
    @classmethod
    def validate_data_directory(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("data directory must be a nonblank path")
        return value.strip()

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
    for directory in [*settings.allowed_directories, settings.data_directory]:
        try:
            # Missing roots are allowed for setup; ingestion never creates an input root.
            info = Path(directory).stat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("configured directory is not a directory")
    return settings
