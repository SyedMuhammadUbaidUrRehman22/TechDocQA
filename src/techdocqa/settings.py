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
    embedding_tokenizer: Literal["bert", "tiktoken"] | None = None
    embedding_model_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    embedding_prefix: str = ""
    embedding_query_prefix: str = ""
    embedding_dimension: int | None = Field(default=None, gt=0)
    embedding_normalization: Literal["l2", "none"] = "none"
    embedding_batch_size: int = Field(default=32, gt=0)
    base_url: str = Field(default="http://127.0.0.1:11434", min_length=1)
    context_window: int | None = Field(default=None, gt=0)
    chat_model_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # "byte-bpe": verified byte-level BPE, so UTF-8 bytes bound the token count. Other tokenizers need their own bound.
    chat_tokenizer: Literal["byte-bpe"] | None = None
    # Reserved for the chat template's role markers around the messages; verified per model.
    chat_template_reserve_tokens: int = Field(default=96, ge=0)
    max_output_tokens: int = Field(default=512, gt=0)
    # None leaves the model's default; false disables a thinking model's reasoning output.
    chat_reasoning: bool | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=0.2)
    # Unset means the FR-16 default: 60 s for a local model, 30 s for an API.
    timeout_seconds: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_generation_bounds(self) -> "ModelSettings":
        if self.timeout_seconds is None:
            self.timeout_seconds = 60 if self.provider == "ollama" else 30
        if self.context_window is not None and self.max_output_tokens + self.chat_template_reserve_tokens >= self.context_window:
            raise ValueError("max_output_tokens plus the template reserve must leave room in context_window")
        return self


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
    # FR-06: "rules" is the P0 segmenter; "spacy" is the P1 policy (nlp extra). Changing it re-chunks every document.
    segmentation: Literal["rules", "spacy"] = "rules"

    @model_validator(mode="after")
    def check_bounds(self) -> "ChunkingSettings":
        if self.overlap >= self.size or self.minimum > self.size:
            raise ValueError("overlap must be below size; minimum cannot exceed size")
        return self


class SufficiencyThresholds(StrictModel):
    """One mode's calibrated FR-18 gate. It applies only while scoring_config_id names the active score scale (Q-07)."""
    min_top_score: float = Field(ge=0, le=1)
    min_chunk_score: float = Field(ge=0, le=1)
    min_supporting_chunks: int = Field(default=1, ge=1)
    # The evaluation run whose scores chose these values.
    calibration_run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    scoring_config_id: str = Field(pattern=r"^sc_[0-9a-f]{64}$")


class SufficiencySettings(StrictModel):
    # Hybrid and reranked scores need their own calibration (P1); no mode borrows another's thresholds.
    bm25: SufficiencyThresholds | None = None
    vector: SufficiencyThresholds | None = None


class RetrievalSettings(StrictModel):
    mode: Literal["bm25", "vector", "hybrid"] = "vector"
    candidate_depth: int = Field(default=20, gt=0)
    top_k: int = Field(default=5, gt=0)
    bm25_k1: float = Field(default=1.2, gt=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    rrf_k: int = Field(default=60, gt=0)
    rerank: bool = False
    rerank_max_candidates: int = Field(default=20, gt=0)
    sufficiency: SufficiencySettings = Field(default_factory=SufficiencySettings)

    @model_validator(mode="after")
    def check_depth(self) -> "RetrievalSettings":
        if self.top_k > self.candidate_depth:
            raise ValueError("top_k cannot exceed candidate_depth")
        for thresholds in (self.sufficiency.bm25, self.sufficiency.vector):
            if thresholds is not None and thresholds.min_supporting_chunks > self.top_k:
                raise ValueError("min_supporting_chunks cannot exceed top_k")
        return self


class AnsweringSettings(StrictModel):
    max_question_characters: int = Field(default=1000, ge=1, le=1000)
    strict_citations: bool = True
    # One JSON line per question under <data>/logs: IDs, hashes and outcomes, never document text or the question.
    query_log: bool = True


class CategorySpec(StrictModel):
    """One FR-09 category; its description is embedded once and frozen before any measurement (P9-6)."""
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9 &/-]*$")
    description: str = Field(min_length=10, max_length=1000)


class EnrichmentSettings(StrictModel):
    """FR-07 to FR-09 (Phase 9). Paths resolve against the configuration file's directory."""
    gazetteer: str = Field(default="gazetteer.toml", min_length=1)
    # Appendix A: below this, an entity is stored with verified=false and never filters (FR-07.3).
    entity_verification_threshold: float = Field(default=0.5, gt=0, le=1)
    keyphrases_per_document: int = Field(default=10, ge=1, le=50)
    keyphrases_per_chunk: bool = False
    # Fewer word tokens than this is "very short" text, which yields an empty list (FR-08.3).
    keyphrase_min_words: int = Field(default=5, ge=1)
    keyphrase_max_words: int = Field(default=4, ge=1, le=10)
    # Whether code blocks feed keyphrase extraction; decided by measurement on the key-term gold set (P9-5).
    keyphrases_include_code: bool = True
    # RAKE's word score: degree / frequency (its default, which favors long rare phrases), degree, or frequency. Also
    # decided by measurement: eval --enrichment scores every metric on the key-term gold set.
    keyphrase_metric: Literal["degree_to_frequency", "word_degree", "word_frequency"] = "degree_to_frequency"
    classification_method: Literal["embedding"] = "embedding"
    max_categories: int = Field(default=3, ge=1, le=3)
    # Cosine similarity, not a probability; set from an evaluation run, as the Phase 8 thresholds are. It applies only
    # while similarity_config_id names the active similarity scale (policy, embedding profile, category descriptions).
    unclassified_threshold: float | None = Field(default=None, ge=-1, le=1)
    calibration_run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    similarity_config_id: str | None = Field(default=None, pattern=r"^cs_[0-9a-f]{64}$")
    categories: list[CategorySpec] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def check_categories(self) -> "EnrichmentSettings":
        names = [category.name.casefold() for category in self.categories]
        if len(set(names)) != len(names) or "unclassified" in names:
            raise ValueError("category names must be unique and cannot be 'unclassified'")
        if len({self.unclassified_threshold is None, self.calibration_run_id is None, self.similarity_config_id is None}) != 1:
            raise ValueError("unclassified_threshold, calibration_run_id and similarity_config_id are set together")
        return self


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
    enrichment: EnrichmentSettings = Field(default_factory=EnrichmentSettings)

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

    def require_chat_profile(self) -> None:
        """Answering needs a model, an explicit window and a verified way to bound prompt tokens."""
        if not all((self.model.chat_model, self.model.context_window, self.model.chat_tokenizer)):
            raise ValueError("chat_model, context_window and chat_tokenizer must be selected")


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
    settings.enrichment.gazetteer = str((base / settings.enrichment.gazetteer).resolve())
    for directory in [*settings.allowed_directories, settings.data_directory]:
        try:
            # Missing roots are allowed for setup; ingestion never creates an input root.
            info = Path(directory).stat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("configured directory is not a directory")
    return settings
