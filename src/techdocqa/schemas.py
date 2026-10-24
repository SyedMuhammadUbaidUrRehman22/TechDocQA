"""Initial request and error contracts; persistence/QA schemas come with their phases."""

from typing import Literal

from pydantic import Field, field_validator

from techdocqa.settings import StrictModel


class SearchFilters(StrictModel):
    document_id: str | None = None
    technology: str | None = None
    category: str | None = None
    entity: str | None = None


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, pattern=r"\S")
    mode: Literal["bm25", "vector", "hybrid"] = "vector"
    top_k: int = Field(default=5, gt=0)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    rerank: bool = False


class QuestionRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    filters: SearchFilters = Field(default_factory=SearchFilters)
    retrieval_config_id: str | None = None


class ErrorDetail(StrictModel):
    code: str
    message: str
    document_id: str | None = None
    stage: str
    retryable: bool = False
    request_id: str


class ErrorResponse(StrictModel):
    error: ErrorDetail


ProcessingStatus = Literal[
    "registered", "extracting", "extraction_failed", "normalized", "chunked",
    "embedded", "indexed", "failed", "superseded", "withdrawn",
]


class OnlineProvenance(StrictModel):
    source_id: str
    canonical_url: str
    final_url: str | None = None
    retrieval_id: str | None = None
    retrieved_at: str | None = None
    content_type: str | None = None
    content_type_header: str | None = None
    snapshot_id: str | None = None
    snapshot_path: str | None = None
    size_bytes: int | None = None
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    original_title: str | None = None
    encoding: str | None = None
    extracted_path: str | None = None
    extracted_hash: str | None = None
    normalized_path: str | None = None
    normalized_hash: str | None = None
    extraction_status: Literal["not_started", "extracted", "extraction_failed"] = "not_started"
    extraction_policy: str | None = None
    configuration_id: str | None = None
    extraction_dependencies: dict[str, str] = Field(default_factory=dict)
    headings: list[dict] = Field(default_factory=list)
    code_spans: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    usage_policy_url: str | None = None
    usage_status: Literal["unverified", "reviewed"] = "unverified"


class RegistrationMetadata(StrictModel):
    title: str | None = Field(default=None, max_length=1000)
    technology: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    version_label: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=4000)
    license: str | None = Field(default=None, max_length=2000)
    language: str = Field(default="en", min_length=1, max_length=50)

    @field_validator("title", "technology", "category", "version_label", "license")
    @classmethod
    def normalize_metadata(cls, value: str | None) -> str | None:
        from techdocqa.privacy import safe_text
        return (safe_text(value) or None) if value is not None else None

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        from techdocqa.privacy import safe_text
        value = safe_text(value)
        if not value:
            raise ValueError("language must not be blank")
        return value

    @field_validator("source_url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        from techdocqa.privacy import safe_source_url
        return safe_source_url(value) if value is not None else None


class RegistrationResult(StrictModel):
    document_id: str
    version_id: str
    status: ProcessingStatus
    deduplicated: bool
    duplicate_of: str | None = None
    run_id: str
    finalized: bool = False
    is_active: bool = False


class ProcessingProvenance(StrictModel):
    snapshot_path: str
    extracted_path: str
    extracted_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_path: str
    normalized_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    documents_path: str
    documents_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalization_policy: str
    unicode_version: str
    resolved_version_id: str | None = None
    original_title: str | None = None
    encoding: str | None = None
    extraction_dependencies: dict[str, str] = Field(default_factory=dict)


class ChunkingProvenance(StrictModel):
    snapshot_path: str
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunking_config_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_count: int = Field(gt=0)
    sentence_count: int = Field(ge=0)
    config: dict


class DocumentRecord(RegistrationResult, RegistrationMetadata):
    source_key: str
    ingested_at: str
    raw_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str | None = None
    filename: str
    doc_type: Literal["pdf", "html", "md", "txt"]
    size_bytes: int = Field(gt=0)
    page_count: int | None = None
    previous_version_id: str | None = None
    online: OnlineProvenance | None = None
    processing: ProcessingProvenance | None = None
    chunking: ChunkingProvenance | None = None
    title_explicit: bool | None = None


class AttemptOutcome(StrictModel):
    attempt_id: str
    input_index: int
    status: Literal["pending", "processed", "skipped", "failed"]
    result: RegistrationResult | None = None
    error: ErrorDetail | None = None
    online: OnlineProvenance | None = None


class RunSummary(StrictModel):
    run_id: str
    status: Literal["running", "completed", "completed_with_errors", "failed"]
    stage: Literal["registration", "normalization", "chunking"] = "registration"
    started_at: str
    finished_at: str | None = None
    processed: int = 0
    skipped: int = 0
    failed: int = 0


class BatchResult(StrictModel):
    run: RunSummary
    outcomes: list[AttemptOutcome]
