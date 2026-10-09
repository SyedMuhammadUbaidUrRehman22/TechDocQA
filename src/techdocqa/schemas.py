"""Initial request and error contracts; persistence/QA schemas come with their phases."""

from typing import Literal

from pydantic import Field

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
