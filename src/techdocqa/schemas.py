"""Request, result and error contracts (section 8)."""

from typing import Literal

from pydantic import Field, field_validator

from techdocqa.settings import StrictModel


class SearchFilters(StrictModel):
    document_id: str | None = None
    technology: str | None = None
    category: str | None = None
    entity: str | None = None


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    mode: Literal["bm25", "vector", "hybrid"] = "vector"
    top_k: int = Field(default=5, gt=0)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    rerank: bool = False


class SearchResult(StrictModel):
    rank: int
    chunk_id: str
    document_id: str
    version_id: str
    title: str | None = None
    section_path: str | None = None
    page: int | None = None
    text: str
    # Raw scores in each retriever's own scale.
    scores: dict[str, float | None]
    ranks: dict[str, int]
    # The mode's documented 0-1 relevance, which the FR-18 thresholds use (Q-07).
    relevance: float | None = None


class SearchResponse(StrictModel):
    retrieval_config_id: str
    mode: Literal["bm25", "vector"]
    degraded: bool = False
    degradation_reason: str | None = None
    results: list[SearchResult]


class LifecycleResult(StrictModel):
    document_id: str
    status: Literal["withdrawn", "deleted"]
    reason: str
    version_id: str | None = None
    removed_entries: int = 0
    removed_files: int = 0
    warnings: list[str] = Field(default_factory=list)


class QuestionRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    filters: SearchFilters = Field(default_factory=SearchFilters)
    retrieval_config_id: str | None = None


class Citation(StrictModel):
    """Every field comes from the registry or the stored chunk artifact, never from model output (FR-17)."""
    label: str
    chunk_id: str
    document_id: str
    version_id: str
    title: str | None = None
    section_path: str | None = None
    source: str
    source_url: str | None = None
    page: int | None = None


class SourceReference(StrictModel):
    document_id: str
    version_id: str
    title: str | None = None
    source: str
    source_url: str | None = None


class QAWarning(StrictModel):
    code: str
    label: str | None = None


class QALatency(StrictModel):
    retrieval: int = 0
    generation: int = 0
    total: int = 0


class QAUsage(StrictModel):
    # Provider-reported counts, when the provider reports them; the bound is what the context budget assumed.
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    prompt_token_bound: int


class SufficiencyCheck(StrictModel):
    """The FR-18 gate on the chunks kept for the prompt. Thresholds are null when the mode has no calibration that applies."""
    calibrated: bool
    # None when no check ran: no calibration, or nothing retrieved to check.
    passed: bool | None = None
    top_score: float | None = None
    supporting_chunks: int | None = None
    min_top_score: float | None = None
    min_chunk_score: float | None = None
    min_supporting_chunks: int | None = None
    calibration_run_id: str | None = None
    relevance_policy: str


class QAResponse(StrictModel):
    """Section 8.3 plus the Q-08 additions: sources, chunk counts, warnings, the sufficiency gate and the generation configuration."""
    status: Literal["answered", "no_evidence", "generation_error"]
    reason: str | None = None
    answer: str | None = None
    citation_verified: bool = False
    citations: list[Citation] = Field(default_factory=list)
    # Non-strict mode only: the chunks the model was given, listed as context rather than per-claim support.
    context_consulted: list[Citation] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    # Chunk IDs placed in the prompt, in label order: evidence[0] is C1.
    evidence: list[str] = Field(default_factory=list)
    chunks_retrieved: int = 0
    chunks_used: int = 0
    mode: Literal["bm25", "vector"]
    retrieval_config_id: str | None = None
    generation_config_id: str | None = None
    provider: str
    model_id: str | None = None
    retryable: bool = False
    warnings: list[QAWarning] = Field(default_factory=list)
    sufficiency: SufficiencyCheck | None = None
    # True once a chat request was sent; a refusal by the sufficiency gate never sends one (AC-18.1).
    llm_called: bool = False
    usage: QAUsage | None = None
    latency_ms: QALatency = Field(default_factory=QALatency)
    request_id: str


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
        from techdocqa.privacy import safe_title
        return (safe_title(value) or None) if value is not None else None

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
    stage: Literal["registration", "normalization", "chunking", "indexing", "enrichment"] = "registration"
    started_at: str
    finished_at: str | None = None
    processed: int = 0
    skipped: int = 0
    failed: int = 0


class BatchResult(StrictModel):
    run: RunSummary
    outcomes: list[AttemptOutcome]
