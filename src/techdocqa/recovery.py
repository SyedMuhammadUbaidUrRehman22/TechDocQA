"""Manual retry of a run's failed attempts (FR-24 behaviour 1, AC-24.1 and AC-24.2; P12-1 and P12-2).

Each failed attempt is classified by its stored `retryable` flag first, then by its run's stage:

- not retryable, at any stage: reported as `permanent` and never rerun;
- retryable, at a processing stage, with its version recorded: rerun through that stage's own function, so every
  rerun is as idempotent as the stage command (stored embeddings are reused, keys are upserted);
- retryable otherwise, at registration or without a recorded version: reported with the command to rerun, because
  the original paths, URLs or version list are not recorded.

A failure is resolved once a later run of the stage succeeded for its version, or once that version is no longer
current or eligible. Without a run ID, the most recent run with an unresolved failure is retried.
"""

import logging

from techdocqa.errors import TechDocQAError
from techdocqa.logs import failure_class, log_event
from techdocqa.schemas import ErrorDetail, RetryItem, RetryResult

COMMANDS = {"registration": "ingest", "normalization": "process", "chunking": "chunk", "indexing": "index",
            "enrichment": "enrich"}


def stage_function(stage: str):
    if stage == "normalization":
        from techdocqa.ingestion.processing import process_versions
        return process_versions
    if stage == "chunking":
        from techdocqa.ingestion.chunks import chunk_versions
        return chunk_versions
    if stage == "indexing":
        from techdocqa.indexing.pipeline import index_versions
        return index_versions
    if stage == "enrichment":
        from techdocqa.enrichment.pipeline import enrich_versions
        return enrich_versions
    raise TechDocQAError("INVALID_STATE", "This stage has no retry.", stage="retry")


def classify(row, stage: str, run_id: str, registry) -> RetryItem:
    error = ErrorDetail.model_validate_json(row["error_json"])
    version_id = row["version_id"]
    if version_id and not registry.failure_outstanding(stage, version_id, run_id):
        action = "resolved"
    elif not error.retryable:
        action = "none"
    elif version_id and stage != "registration":
        action = "retried"
    else:
        action = "rerun_command"
    return RetryItem(attempt_id=row["attempt_id"], document_id=row["document_id"], version_id=version_id, code=error.code,
                     stage=error.stage, failure=failure_class(error.retryable), action=action,
                     command=COMMANDS[stage] if action == "rerun_command" else None)


def retry_run(run_id: str | None, settings, registry) -> RetryResult:
    if run_id is None:
        run_id = registry.latest_outstanding_run()
        if run_id is None:
            log_event("recovery", "RETRY_FINISHED", retry_of=None, rerun_run_id=None, remaining=0)
            return RetryResult()
    registry.get_run(run_id)  # NOT_FOUND for an unknown run.
    stage = registry.run_stage(run_id)
    items = [classify(row, stage, run_id, registry) for row in registry.failed_attempts(run_id)]
    for item in items:
        log_event("recovery", "RETRY_DECISION", level=logging.INFO if item.action in {"retried", "resolved"} else logging.WARNING,
                  run_id=run_id, document_id=item.document_id, attempt_id=item.attempt_id, version_id=item.version_id,
                  code=item.code, stage=item.stage, failure=item.failure, action=item.action, command=item.command)
    versions = list(dict.fromkeys(item.version_id for item in items if item.action == "retried"))
    rerun = stage_function(stage)(versions, settings, registry) if versions else None
    remaining = sum(item.action in {"none", "rerun_command"} for item in items) + (rerun.run.failed if rerun else 0)
    log_event("recovery", "RETRY_FINISHED", level=logging.INFO if remaining == 0 else logging.WARNING, run_id=run_id,
              retry_of=run_id, rerun_run_id=rerun.run.run_id if rerun else None, retried=len(versions), remaining=remaining)
    return RetryResult(retry_of=run_id, stage=stage, items=items, rerun=rerun, remaining=remaining)
