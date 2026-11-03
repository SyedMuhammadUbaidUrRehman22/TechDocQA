"""Benchmark questions with stable relevance labels: a source key plus a text anchor or section, never a chunk ID."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from techdocqa.errors import TechDocQAError
from techdocqa.settings import StrictModel


class RelevantItem(StrictModel):
    source_key: str = Field(min_length=1)
    # Verbatim passage, matched case-insensitively with whitespace collapsed, so it survives re-chunking.
    anchor: str | None = Field(default=None, min_length=3, max_length=500)
    # Heading path joined by " > "; subsections match too.
    section: str | None = Field(default=None, min_length=1)
    grade: Literal[0, 1, 2] = 2

    @model_validator(mode="after")
    def locate(self):
        if self.anchor is None and self.section is None:
            raise ValueError("an item needs an anchor or a section")
        return self


class Question(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    question: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    technology: str | None = None
    type: Literal["factual", "how_to", "identifier"]
    unanswerable: bool = False
    relevant: list[RelevantItem] = Field(default_factory=list)
    review: Literal["draft", "reviewed"]

    @model_validator(mode="after")
    def expected_items(self):
        graded = any(item.grade > 0 for item in self.relevant)
        # AC-19.5: no expected items is only valid when the question says so.
        if self.unanswerable == graded:
            raise ValueError("an answerable question needs a relevant item; an unanswerable one has none")
        return self


class Dataset(StrictModel):
    dataset_id: str
    path: str
    sha256: str
    questions: list[Question]


def invalid(line: int, reason: str) -> TechDocQAError:
    return TechDocQAError("INVALID_BENCHMARK", f"Benchmark line {line}: {reason}.", stage="evaluation")


def load_dataset(path: Path) -> Dataset:
    """The hash covers the exact bytes, so any label or review change is a new dataset version."""
    try:
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise TechDocQAError("BENCHMARK_NOT_READABLE", "The benchmark file cannot be read as UTF-8.", stage="evaluation") from None
    questions, seen = [], set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            question = Question.model_validate(json.loads(line))
        except json.JSONDecodeError:
            raise invalid(number, "not valid JSON") from None
        except ValidationError as error:
            raise invalid(number, error.errors()[0]["msg"].removeprefix("Value error, ")) from None
        if question.id in seen:
            raise invalid(number, "duplicate question id")
        seen.add(question.id)
        questions.append(question)
    if not questions:
        raise TechDocQAError("INVALID_BENCHMARK", "The benchmark has no questions.", stage="evaluation")
    return Dataset(dataset_id=Path(path).stem, path=Path(path).as_posix(), sha256=hashlib.sha256(raw).hexdigest(), questions=questions)
