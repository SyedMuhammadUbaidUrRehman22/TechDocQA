"""Safe domain errors: messages never interpolate untrusted input."""

from uuid import uuid4

from techdocqa.schemas import ErrorDetail, ErrorResponse


class TechDocQAError(Exception):
    def __init__(self, code: str, message: str, *, stage: str = "registration",
                 retryable: bool = False, document_id: str | None = None):
        super().__init__(message)
        self.response = ErrorResponse(error=ErrorDetail(
            code=code, message=message, stage=stage, retryable=retryable,
            document_id=document_id, request_id=f"req_{uuid4().hex}",
        ))
