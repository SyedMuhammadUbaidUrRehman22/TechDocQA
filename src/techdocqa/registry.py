"""SQLite source registrations and attempts; no extracted document text is stored."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.safety import ValidatedSource
from techdocqa.privacy import safe_text
from techdocqa.schemas import (
    AttemptOutcome, BatchResult, DocumentRecord, ErrorDetail, RegistrationMetadata,
    OnlineProvenance, RegistrationResult, RunSummary,
)

APPLICATION_ID = 0x54445141
SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    source_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    current_version_id TEXT REFERENCES registrations(version_id),
    created_at TEXT NOT NULL
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('running','completed','completed_with_errors','failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    processed INTEGER NOT NULL DEFAULT 0 CHECK(processed >= 0),
    skipped INTEGER NOT NULL DEFAULT 0 CHECK(skipped >= 0),
    failed INTEGER NOT NULL DEFAULT 0 CHECK(failed >= 0)
);
CREATE TABLE registrations (
    version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    raw_hash TEXT NOT NULL CHECK(length(raw_hash)=64 AND raw_hash NOT GLOB '*[^0-9a-f]*'),
    content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
    doc_type TEXT NOT NULL CHECK(doc_type IN ('pdf','html','md','txt')),
    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
    page_count INTEGER CHECK(page_count > 0),
    status TEXT NOT NULL CHECK(status IN (
        'registered','extracting','extraction_failed','normalized','chunked','embedded',
        'indexed','failed','superseded','withdrawn')),
    finalized INTEGER NOT NULL DEFAULT 0 CHECK(finalized IN (0,1)),
    is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)),
    ingested_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    previous_version_id TEXT REFERENCES registrations(version_id),
    duplicate_of TEXT REFERENCES documents(document_id),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    UNIQUE(document_id, raw_hash),
    UNIQUE(document_id, sequence),
    CHECK((finalized=0 AND content_hash IS NULL AND is_active=0) OR
          (finalized=1 AND content_hash IS NOT NULL))
);
CREATE UNIQUE INDEX one_active_registration ON registrations(document_id) WHERE is_active=1;
CREATE INDEX registrations_raw_hash ON registrations(raw_hash);
CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    input_index INTEGER NOT NULL CHECK(input_index >= 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processed','skipped','failed')),
    document_id TEXT REFERENCES documents(document_id),
    version_id TEXT REFERENCES registrations(version_id),
    result_json TEXT,
    error_json TEXT,
    UNIQUE(run_id,input_index)
);
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    run_id TEXT REFERENCES runs(run_id),
    attempt_id TEXT REFERENCES attempts(attempt_id),
    document_id TEXT REFERENCES documents(document_id),
    version_id TEXT REFERENCES registrations(version_id),
    status TEXT,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    stage TEXT NOT NULL,
    error_json TEXT
);
CREATE INDEX events_document ON events(document_id,event_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def storage_error(error: sqlite3.Error) -> TechDocQAError:
    busy = getattr(error, "sqlite_errorcode", 0) & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    return TechDocQAError(
        "REGISTRY_BUSY" if busy else "REGISTRY_ERROR",
        "Registry is busy; retry the operation." if busy else "Registry operation failed safely.",
        stage="registry", retryable=busy,
    )


class Registry:
    def __init__(self, path: Path, *, timeout: float = 5):
        self.path = Path(path)
        self.connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            with self.transaction():
                version = self.execute("PRAGMA user_version").fetchone()[0]
                app_id = self.execute("PRAGMA application_id").fetchone()[0]
                if version == 0 and app_id == 0:
                    if self.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone():
                        raise TechDocQAError("REGISTRY_SCHEMA_MISMATCH", "Registry schema is not recognized.", stage="registry")
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            self.execute(statement)
                    self.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif version != SCHEMA_VERSION or app_id != APPLICATION_ID:
                    raise TechDocQAError("REGISTRY_SCHEMA_MISMATCH", "Registry schema version is unsupported.", stage="registry")
        except (sqlite3.Error, OSError) as error:
            self.close()
            if isinstance(error, sqlite3.Error):
                raise storage_error(error) from None
            raise TechDocQAError("REGISTRY_NOT_ACCESSIBLE", "Registry storage is not accessible.", stage="registry") from None
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def execute(self, sql: str, parameters=()):
        try:
            return self.connection.execute(sql, parameters)
        except sqlite3.Error as error:
            raise storage_error(error) from None

    @contextmanager
    def transaction(self):
        self.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.execute("COMMIT")
        except BaseException:
            self.connection.rollback()
            raise

    @contextmanager
    def registration_lock(self):
        """An OS lock releases on process death, allowing safe orphan-run recovery."""
        try:
            lock = self.path.with_suffix(self.path.suffix + ".lock").open("a+b")
        except OSError:
            raise TechDocQAError("REGISTRY_NOT_ACCESSIBLE", "Registration lock is inaccessible.", stage="registry") from None
        acquired = False
        try:
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                raise TechDocQAError("REGISTRY_BUSY", "Another registration run is active.", stage="registry", retryable=True) from None
            yield
        finally:
            if acquired:
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    def start_run(self, input_count: int) -> tuple[str, list[str]]:
        run_id = new_id("run")
        attempts = [new_id("att") for _ in range(input_count)]
        with self.transaction():
            self.execute("INSERT INTO runs(run_id,status,started_at) VALUES (?,'running',?)", (run_id, utc_now()))
            for index, attempt_id in enumerate(attempts):
                self.execute("INSERT INTO attempts(attempt_id,run_id,input_index) VALUES (?,?,?)", (attempt_id, run_id, index))
        return run_id, attempts

    def pending_attempt(self, attempt_id: str):
        row = self.execute("SELECT a.* FROM attempts a JOIN runs r USING(run_id) WHERE attempt_id=? AND a.status='pending' AND r.status='running'", (attempt_id,)).fetchone()
        if row is None:
            raise TechDocQAError("INVALID_STATE", "Attempt is not pending in an active run.", stage="registry")
        return row

    def event(self, *, run_id=None, attempt_id=None, document_id=None, version_id=None,
              status=None, decision: str, reason: str, stage="registration", error=None):
        self.execute("""INSERT INTO events(timestamp,run_id,attempt_id,document_id,version_id,status,decision,reason,stage,error_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (utc_now(), run_id, attempt_id, document_id, version_id, status,
                      decision, reason, stage, error.model_dump_json() if error else None))

    def register(self, source: ValidatedSource, metadata: RegistrationMetadata,
                 logical_name: str | None, attempt_id: str, *,
                 online: OnlineProvenance | None = None) -> RegistrationResult:
        filename = safe_text(source.path.name)
        normalized_name = os.path.normcase(filename)
        logical_name = safe_text(logical_name) if logical_name is not None else None
        if logical_name == "":
            raise TechDocQAError("INVALID_METADATA", "Logical name must not be blank.")
        source_key = json.dumps([normalized_name, logical_name], ensure_ascii=False, separators=(",", ":"))
        source_path = os.path.normcase(str(source.path))
        if online is not None:
            from techdocqa.ingestion.urls import canonical_url
            try:
                source_key = canonical_url(online.canonical_url)
            except ValueError:
                raise TechDocQAError("INVALID_METADATA", "Online source identity is invalid.") from None
            if (source_key != online.canonical_url or metadata.source_url != source_key or logical_name is not None
                    or online.snapshot_id != source.raw_hash or online.extraction_status != "extracted"
                    or source.doc_type != "html"):
                raise TechDocQAError("INVALID_METADATA", "Online source identity is inconsistent.")
            source_path = source_key
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            run_id = attempt["run_id"]
            document = self.execute("SELECT * FROM documents WHERE source_key=?", (source_key,)).fetchone()
            if document and document["source_path"] != source_path:
                raise TechDocQAError("SOURCE_KEY_COLLISION", "Source identity is already bound to another location; use a logical name.")
            now = utc_now()
            document_id = document["document_id"] if document else new_id("doc")
            if document is None:
                self.execute("INSERT INTO documents(document_id,source_key,source_path,filename,created_at) VALUES (?,?,?,?,?)",
                             (document_id, source_key, source_path, filename, now))
            existing = self.execute("SELECT * FROM registrations WHERE document_id=? AND raw_hash=?", (document_id, source.raw_hash)).fetchone()
            deduplicated = existing is not None and existing["status"] == "registered"
            if existing:
                version_id, duplicate_of = existing["version_id"], existing["duplicate_of"]
                decision = "DUPLICATE_SKIPPED" if deduplicated else "RETRY_REGISTERED"
                reason = "Unchanged bytes; existing registration metadata retained." if deduplicated else "Retry reused the existing byte registration."
                if existing["status"] not in {"registered", "failed", "extraction_failed"}:
                    raise TechDocQAError("INVALID_STATE", "This processing state requires the later ingestion pipeline.", document_id=document_id)
                self.execute("UPDATE registrations SET status='registered' WHERE version_id=?", (version_id,))
            else:
                version_id = new_id("ver")
                match = self.execute("SELECT document_id FROM registrations WHERE raw_hash=? AND document_id<>? ORDER BY ingested_at,version_id LIMIT 1", (source.raw_hash, document_id)).fetchone()
                duplicate_of = match[0] if match else None
                previous = document["current_version_id"] if document else None
                sequence = self.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM registrations WHERE document_id=?", (document_id,)).fetchone()[0]
                stored_metadata = metadata.model_copy(update={"title": metadata.title or filename})
                metadata_values = stored_metadata.model_dump()
                if online is not None:
                    metadata_values["online"] = online.model_dump()
                self.execute("""INSERT INTO registrations(version_id,document_id,run_id,raw_hash,doc_type,size_bytes,page_count,status,ingested_at,metadata_json,previous_version_id,duplicate_of,sequence)
                                VALUES (?,?,?,?,?,?,?,'registered',?,?,?,?,?)""",
                             (version_id, document_id, run_id, source.raw_hash, source.doc_type,
                              source.size_bytes, source.page_count, now, json.dumps(metadata_values), previous, duplicate_of, sequence))
                decision = "CHANGED_BYTES_REGISTERED" if previous else "REGISTERED"
                reason = "New byte registration; normalized identity remains undecided."
            self.execute("UPDATE documents SET current_version_id=? WHERE document_id=?", (version_id, document_id))
            result = RegistrationResult(document_id=document_id, version_id=version_id, status="registered",
                                        deduplicated=deduplicated, duplicate_of=duplicate_of, run_id=run_id)
            result_values = result.model_dump()
            if online is not None:
                result_values["online"] = online.model_dump()
            self.execute("UPDATE attempts SET status=?,document_id=?,version_id=?,result_json=? WHERE attempt_id=?",
                         ("skipped" if deduplicated else "processed", document_id, version_id, json.dumps(result_values), attempt_id))
            if deduplicated:
                self.execute("UPDATE runs SET skipped=skipped+1 WHERE run_id=?", (run_id,))
            else:
                self.execute("UPDATE runs SET processed=processed+1 WHERE run_id=?", (run_id,))
            self.event(run_id=run_id, attempt_id=attempt_id, document_id=document_id, version_id=version_id,
                       status="registered", decision=decision, reason=reason)
        return result

    def fail_attempt(self, attempt_id: str, error: ErrorDetail, *, online: OnlineProvenance | None = None):
        error = error.model_copy(update={"message": safe_text(error.message)})
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            context = json.dumps({"online": online.model_dump()}) if online is not None else None
            self.execute("UPDATE attempts SET status='failed',error_json=?,result_json=? WHERE attempt_id=?", (error.model_dump_json(), context, attempt_id))
            self.execute("UPDATE runs SET failed=failed+1 WHERE run_id=?", (attempt["run_id"],))
            self.event(run_id=attempt["run_id"], attempt_id=attempt_id, decision="REGISTRATION_FAILED",
                       reason=error.message, stage=error.stage, error=error)

    def fail_registration(self, version_id: str):
        """Record a later processing failure without superseding another registration."""
        with self.transaction():
            row = self.execute("SELECT * FROM registrations WHERE version_id=?", (version_id,)).fetchone()
            if row is None:
                raise TechDocQAError("NOT_FOUND", "Registration was not found.", stage="registry")
            if row["finalized"] or row["status"] != "registered":
                raise TechDocQAError("INVALID_STATE", "Only a pending registered candidate can fail here.", stage="registry")
            self.execute("UPDATE registrations SET status='failed' WHERE version_id=?", (version_id,))
            error = TechDocQAError("PROCESSING_FAILED", "Later processing failed.", stage="processing", document_id=row["document_id"]).response.error
            self.event(document_id=row["document_id"], version_id=version_id, status="failed",
                       decision="PROCESSING_FAILED", reason=error.message, stage=error.stage, error=error)

    def finish_run(self, run_id: str):
        with self.transaction():
            counts = {row[0]: row[1] for row in self.execute("SELECT status,COUNT(*) FROM attempts WHERE run_id=? GROUP BY status", (run_id,)).fetchall()}
            if counts.get("pending"):
                raise TechDocQAError("INVALID_STATE", "Run still has pending attempts.", stage="registry")
            failed = counts.get("failed", 0)
            good = counts.get("processed", 0) + counts.get("skipped", 0)
            status = "completed_with_errors" if failed and good else "failed" if failed else "completed"
            cursor = self.execute("UPDATE runs SET status=?,finished_at=?,processed=?,skipped=?,failed=? WHERE run_id=? AND status='running'",
                                 (status, utc_now(), counts.get("processed", 0), counts.get("skipped", 0), failed, run_id))
            if cursor.rowcount != 1:
                raise TechDocQAError("INVALID_STATE", "Run is not active.", stage="registry")

    def recover_interrupted_runs(self):
        """Caller must hold registration_lock; never infer process death from a PID."""
        runs = self.execute("SELECT run_id FROM runs WHERE status='running'").fetchall()
        for run in runs:
            attempts = self.execute("SELECT attempt_id FROM attempts WHERE run_id=? AND status='pending' ORDER BY input_index", (run[0],)).fetchall()
            for attempt in attempts:
                error = TechDocQAError("RUN_INTERRUPTED", "Registration was interrupted; re-register the input.", retryable=True).response.error
                self.fail_attempt(attempt[0], error)
            self.finish_run(run[0])

    def get_run(self, run_id: str) -> BatchResult:
        row = self.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise TechDocQAError("NOT_FOUND", "Run was not found.", stage="registry")
        outcomes = []
        for attempt in self.execute("SELECT * FROM attempts WHERE run_id=? ORDER BY input_index", (run_id,)).fetchall():
            result_values = json.loads(attempt["result_json"]) if attempt["result_json"] else {}
            online_values = result_values.pop("online", None)
            outcomes.append(AttemptOutcome(
                attempt_id=attempt["attempt_id"], input_index=attempt["input_index"], status=attempt["status"],
                result=RegistrationResult.model_validate(result_values) if result_values else None,
                error=ErrorDetail.model_validate_json(attempt["error_json"]) if attempt["error_json"] else None,
                online=OnlineProvenance.model_validate(online_values) if online_values is not None else None,
            ))
        return BatchResult(run=RunSummary(**dict(row)), outcomes=outcomes)

    def document_record(self, row) -> DocumentRecord:
        values = dict(row)
        values.update(json.loads(values.pop("metadata_json")))
        values.pop("sequence")
        values["finalized"] = bool(values["finalized"])
        values["is_active"] = bool(values["is_active"])
        return DocumentRecord(**values, deduplicated=False)

    def get_document(self, document_id: str) -> DocumentRecord:
        row = self.execute("""SELECT r.*,d.source_key,d.filename FROM documents d
                              JOIN registrations r ON r.version_id=d.current_version_id WHERE d.document_id=?""", (document_id,)).fetchone()
        if row is None:
            raise TechDocQAError("NOT_FOUND", "Document was not found.", stage="registry")
        return self.document_record(row)

    def list_documents(self, status: str | None = None) -> list[DocumentRecord]:
        rows = self.execute("""SELECT r.*,d.source_key,d.filename FROM documents d
                               JOIN registrations r ON r.version_id=d.current_version_id
                               WHERE (? IS NULL OR r.status=?) ORDER BY d.source_key,d.document_id""", (status, status)).fetchall()
        return [self.document_record(row) for row in rows]

    def history(self, document_id: str) -> dict:
        self.get_document(document_id)
        rows = self.execute("""SELECT r.*,d.source_key,d.filename FROM registrations r
                               JOIN documents d USING(document_id) WHERE document_id=? ORDER BY sequence""", (document_id,)).fetchall()
        events = []
        for row in self.execute("SELECT * FROM events WHERE document_id=? ORDER BY event_id", (document_id,)).fetchall():
            event = dict(row)
            event["error"] = json.loads(event.pop("error_json")) if event["error_json"] else None
            event.pop("error_json", None)
            events.append(event)
        return {"document_id": document_id, "registrations": [self.document_record(row).model_dump() for row in rows], "events": events}
