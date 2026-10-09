import pytest
from pydantic import ValidationError

from techdocqa.schemas import ErrorDetail, ErrorResponse, QuestionRequest, SearchRequest


@pytest.mark.parametrize("question", ["", "  ", "x" * 1001])
def test_invalid_questions(question):
    with pytest.raises(ValidationError):
        QuestionRequest(question=question)


def test_search_filters_and_error_json_round_trip():
    request = SearchRequest(query="HTTP/2", filters={"entity": "Redis"})
    assert request.filters.entity == "Redis"
    error = ErrorResponse(error=ErrorDetail(
        code="INVALID_QUESTION", message="Question is invalid", stage="question", request_id="req_test",
    ))
    assert ErrorResponse.model_validate_json(error.model_dump_json()) == error
    assert error.error.document_id is None
