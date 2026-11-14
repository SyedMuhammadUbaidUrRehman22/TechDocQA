"""Structured JSON-lines logs (FR-24 behaviour 3, P12-4).

Every line carries the six required fields (`REQUIRED`) plus an `event` code and safe values: IDs, error codes,
stages, counts and flags. Document text, questions and provider messages are never passed in. Strings are masked
like every other recorded message (`privacy.safe_text`), and values that are not plain data are dropped, never
turned into text.

Only TechDocQA's own loggers write here; third-party library loggers are not routed into the file, because their
messages can hold URLs, secrets or document text. Without `configure`, as in library use or most tests, nothing is
written. The query log, `qa.jsonl`, is written by the answering module and carries the same six fields.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from techdocqa.privacy import safe_text

LOGGER = "techdocqa"
FILE = "techdocqa.jsonl"
REQUIRED = ("timestamp", "level", "component", "run_id", "document_id", "request_id")
SCALARS = (str, int, float, bool, type(None))

# A library's records go nowhere unless a command configures the file, and never to Python's last-resort stderr.
logging.getLogger(LOGGER).addHandler(logging.NullHandler())


def clean(value):
    """Plain data only: strings are masked, and anything that is not a scalar, list or dict is dropped."""
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, SCALARS):
        return value
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value if isinstance(item, (*SCALARS, list, tuple, dict))]
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items() if isinstance(item, (*SCALARS, list, tuple, dict))}
    return None


def utc_timestamp(seconds: float | None = None) -> str:
    moment = datetime.now(timezone.utc) if seconds is None else datetime.fromtimestamp(seconds, timezone.utc)
    return moment.isoformat()


class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = getattr(record, "techdocqa", {})
        entry = {
            "timestamp": utc_timestamp(record.created), "level": record.levelname.lower(),
            "component": record.name.removeprefix(LOGGER + ".") if record.name != LOGGER else LOGGER,
            "run_id": context.get("run_id"), "document_id": context.get("document_id"),
            "request_id": context.get("request_id"),
            # The message is an event code; record arguments are never interpolated.
            "event": str(record.msg),
        }
        for key, value in clean(context.get("fields", {})).items():
            entry.setdefault(key, value)
        return json.dumps({key: clean(value) for key, value in entry.items()}, ensure_ascii=True, sort_keys=True)


def handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in logger.handlers if getattr(handler, "techdocqa_log", False)]


def close() -> None:
    """Stop writing the log file and release it."""
    logger = logging.getLogger(LOGGER)
    for handler in handlers(logger):
        logger.removeHandler(handler)
        handler.close()


def configure(settings) -> Path | None:
    """Send TechDocQA's records to <data>/logs/techdocqa.jsonl, replacing any earlier file; None when logs are off."""
    close()
    logger = logging.getLogger(LOGGER)
    logger.propagate = False
    if not settings.logs.enabled:
        return None
    path = Path(settings.data_directory) / "logs" / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8", delay=True)
    handler.techdocqa_log = True
    handler.setFormatter(JsonLines())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def log_event(component: str, event: str, *, level: int = logging.INFO, run_id: str | None = None,
              document_id: str | None = None, request_id: str | None = None, **fields) -> None:
    logger = logging.getLogger(f"{LOGGER}.{component}")
    if logger.isEnabledFor(level):
        logger.log(level, event, extra={"techdocqa": {"run_id": run_id, "document_id": document_id,
                                                      "request_id": request_id, "fields": fields}})


def failure_class(retryable: bool) -> str:
    """FR-24 behaviour 1: a failure is retryable or permanent; `ErrorDetail` keeps the flag (P12-2)."""
    return "retryable" if retryable else "permanent"
