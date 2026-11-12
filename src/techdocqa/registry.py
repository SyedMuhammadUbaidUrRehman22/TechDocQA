"""SQLite source registrations and attempts; no extracted document text is stored."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote
from uuid import uuid4

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.safety import ValidatedSource
from techdocqa.privacy import safe_text, safe_title
from techdocqa.schemas import (
    AttemptOutcome, BatchResult, DocumentRecord, ErrorDetail, RegistrationMetadata,
    OnlineProvenance, ProcessingProvenance, RegistrationResult, RunSummary, ChunkingProvenance,
)

APPLICATION_ID = 0x54445141
SCHEMA_VERSION = 3
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
# Additive: stored vectors let the derived vector store be rebuilt without a model.
SCHEMA_V2 = """
CREATE TABLE embedding_profiles (
    profile_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    embedding_model_id TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK(dimension > 0),
    normalization TEXT NOT NULL,
    metric TEXT NOT NULL,
    collection TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE embeddings (
    chunk_key TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES embedding_profiles(profile_id),
    text_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX embeddings_text ON embeddings(text_hash);
CREATE TABLE chunk_embeddings (
    chunk_id TEXT NOT NULL,
    profile_id TEXT NOT NULL REFERENCES embedding_profiles(profile_id),
    version_id TEXT NOT NULL REFERENCES registrations(version_id),
    chunk_key TEXT NOT NULL,
    chunking_config_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('embedded','embedding_failed')),
    reason TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(chunk_id,profile_id)
);
CREATE INDEX chunk_embeddings_version ON chunk_embeddings(version_id);
CREATE INDEX chunk_embeddings_key ON chunk_embeddings(chunk_key);
CREATE TABLE verified_entities (
    chunk_id TEXT NOT NULL,
    version_id TEXT NOT NULL REFERENCES registrations(version_id),
    entity TEXT NOT NULL,
    PRIMARY KEY(chunk_id,entity)
);
CREATE INDEX verified_entities_entity ON verified_entities(entity);
"""
# Additive (Phase 9, P9-8): enrichment rows carry the chunk identity they were derived from, so a re-chunk or a
# configuration change makes them stale instead of silently reused.
SCHEMA_V3 = """
CREATE TABLE enrichments (
    version_id TEXT PRIMARY KEY REFERENCES registrations(version_id),
    chunking_config_id TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    enrichment_config_id TEXT NOT NULL,
    entity_config_id TEXT NOT NULL,
    keyphrase_config_id TEXT NOT NULL,
    classifier_config_id TEXT NOT NULL,
    entity_count INTEGER NOT NULL CHECK(entity_count >= 0),
    verified_count INTEGER NOT NULL CHECK(verified_count >= 0),
    keyphrase_status TEXT NOT NULL CHECK(keyphrase_status IN ('extracted','unavailable')),
    classification_status TEXT NOT NULL CHECK(classification_status IN (
        'classified','unclassified','not_calibrated','not_embedded','not_configured')),
    run_id TEXT REFERENCES runs(run_id),
    updated_at TEXT NOT NULL
);
CREATE TABLE entities (
    entity_id INTEGER PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES registrations(version_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    chunk_id TEXT NOT NULL,
    text TEXT NOT NULL,
    canonical TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('TECHNOLOGY','COMPONENT','CONCEPT','PROTOCOL','IDENTIFIER')),
    source TEXT NOT NULL CHECK(source IN ('rule','model')),
    rule_id TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    verified INTEGER NOT NULL CHECK(verified IN (0,1)),
    chunk_start INTEGER NOT NULL CHECK(chunk_start >= 0),
    chunk_end INTEGER NOT NULL CHECK(chunk_end > chunk_start),
    document_index INTEGER NOT NULL CHECK(document_index >= 0),
    document_start INTEGER NOT NULL CHECK(document_start >= 0),
    document_end INTEGER NOT NULL CHECK(document_end > document_start)
);
CREATE INDEX entities_version ON entities(version_id);
CREATE INDEX entities_chunk ON entities(chunk_id);
CREATE TABLE keyphrases (
    version_id TEXT NOT NULL REFERENCES registrations(version_id),
    scope TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK(rank > 0),
    phrase TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY(version_id, scope, rank)
);
CREATE TABLE document_categories (
    version_id TEXT NOT NULL REFERENCES registrations(version_id),
    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 3),
    category TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= -1 AND confidence <= 1),
    assigned INTEGER NOT NULL CHECK(assigned IN (0,1)),
    source TEXT NOT NULL CHECK(source IN ('embedding')),
    PRIMARY KEY(version_id, rank)
);
CREATE TABLE category_embeddings (
    key TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES embedding_profiles(profile_id),
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL
);
"""
ENRICHMENT_TABLES = ("entities", "keyphrases", "document_categories", "verified_entities", "enrichments")
RUN_STARTED = {"normalization": "PROCESSING_RUN_STARTED", "chunking": "CHUNKING_RUN_STARTED", "indexing": "INDEXING_RUN_STARTED",
               "enrichment": "ENRICHMENT_RUN_STARTED"}
# A version eligible for retrieval; indexing state is checked separately per retriever.
ELIGIBLE = "r.finalized=1 AND r.is_active=1 AND r.duplicate_of IS NULL"
SQL_BATCH = 400
ARTIFACT_FIELDS = {"processing": ("snapshot_path", "extracted_path", "normalized_path", "documents_path"),
                   "chunking": ("snapshot_path",), "online": ("snapshot_path", "extracted_path", "normalized_path")}


def artifact_paths(values: dict) -> set[str]:
    return {values[section][field] for section, fields in ARTIFACT_FIELDS.items() if values.get(section)
            for field in fields if values[section].get(field)}


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
        self.timeout = timeout
        self.connection = None
        self.backup_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            upgrades = {1: SCHEMA_V2 + SCHEMA_V3, 2: SCHEMA_V3}
            with self.transaction():
                version, app_id = self.version_state()
                if version == 0 and app_id == 0:
                    if self.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone():
                        raise TechDocQAError("REGISTRY_SCHEMA_MISMATCH", "Registry schema is not recognized.", stage="registry")
                    self.apply_schema(SCHEMA + SCHEMA_V2 + SCHEMA_V3)
                    self.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif version in upgrades and app_id == APPLICATION_ID:
                    # The write lock is held from before the copy until the migration commits, so the backup is exactly
                    # what is migrated, and a concurrent opener waits, then finds the registry already upgraded.
                    self.backup_before_upgrade(version)
                    self.apply_schema(upgrades[version])
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

    def version_state(self) -> tuple[int, int]:
        return (self.execute("PRAGMA user_version").fetchone()[0], self.execute("PRAGMA application_id").fetchone()[0])

    def backup_before_upgrade(self, version: int):
        """Copy through SQLite's backup API, then reopen the copy: integrity and every table's row count must match.

        Runs inside the migration's BEGIN IMMEDIATE transaction, so nothing can commit between the copy and the upgrade.
        SQLite refuses to back up from a connection in a write transaction (sqlite3_backup_step returns SQLITE_BUSY, which
        Python retries forever), so the copy is read through a second, read-only connection. This connection holds the
        write lock but has written nothing yet, so the reader sees exactly the committed state that is about to be
        migrated. The reader is closed before the migration commits, which needs every reader gone.
        The file is created exclusively, so this process only ever writes, or removes, a backup it made itself.
        """
        tables = [row[0] for row in self.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        copy = target = source = None
        try:
            for number in range(1000):
                suffix = f".pre-v{SCHEMA_VERSION}.bak" if number == 0 else f".pre-v{SCHEMA_VERSION}.{number}.bak"
                candidate = self.path.with_name(self.path.name + suffix)
                try:
                    candidate.open("xb").close()
                except FileExistsError:
                    continue
                target = candidate
                break
            if target is None:
                raise ValueError
            copy = sqlite3.connect(target)
            source = sqlite3.connect(f"file:{quote(self.path.resolve().as_posix(), safe='/:')}?mode=ro", uri=True,
                                     timeout=self.timeout)
            source.backup(copy)
            source.close()
            source = None
            live = {name: self.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
            copied = {name: copy.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
            if (copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or copied != live
                    or copy.execute("PRAGMA user_version").fetchone()[0] != version):
                raise ValueError
        except (sqlite3.Error, OSError, ValueError):
            for handle in (source, copy):
                if handle is not None:
                    handle.close()
            source = copy = None
            if target is not None:
                target.unlink(missing_ok=True)
            raise TechDocQAError("REGISTRY_BACKUP_FAILED", "The registry could not be backed up before its upgrade; nothing was changed.",
                                 stage="registry") from None
        finally:
            for handle in (source, copy):
                if handle is not None:
                    handle.close()
        self.backup_path = target

    def apply_schema(self, schema: str):
        for statement in schema.split(";"):
            if statement.strip():
                self.execute(statement)

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

    def start_run(self, input_count: int, *, stage: str = "registration") -> tuple[str, list[str]]:
        run_id = new_id("run")
        attempts = [new_id("att") for _ in range(input_count)]
        with self.transaction():
            self.execute("INSERT INTO runs(run_id,status,started_at) VALUES (?,'running',?)", (run_id, utc_now()))
            for index, attempt_id in enumerate(attempts):
                self.execute("INSERT INTO attempts(attempt_id,run_id,input_index) VALUES (?,?,?)", (attempt_id, run_id, index))
            if stage in RUN_STARTED:
                self.event(run_id=run_id, decision=RUN_STARTED[stage], reason="Offline candidate processing.", stage=stage)
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
            deduplicated = existing is not None and (existing["status"] == "registered" or existing["finalized"]
                or json.loads(existing["metadata_json"]).get("processing", {}).get("resolved_version_id"))
            deduplicated = bool(deduplicated)
            if existing:
                version_id, duplicate_of = existing["version_id"], existing["duplicate_of"]
                resolved = json.loads(existing["metadata_json"]).get("processing", {}).get("resolved_version_id")
                reactivated = self.reactivate(resolved or version_id)
                decision = "DOCUMENT_REACTIVATED" if reactivated else "DUPLICATE_SKIPPED" if deduplicated else "RETRY_REGISTERED"
                reason = ("Re-ingesting withdrawn content reactivated it." if reactivated else
                          "Unchanged bytes; existing registration metadata retained." if deduplicated else "Retry reused the existing byte registration.")
                if not deduplicated and existing["status"] not in {"failed", "extraction_failed"}:
                    raise TechDocQAError("INVALID_STATE", "This processing state requires the later ingestion pipeline.", document_id=document_id)
                if not existing["finalized"] and existing["status"] != "normalized":
                    self.execute("UPDATE registrations SET status='registered' WHERE version_id=?", (version_id,))
                if reactivated:
                    deduplicated = False
                    duplicate_of = self.execute("SELECT duplicate_of FROM registrations WHERE version_id=?", (version_id,)).fetchone()[0]
            else:
                version_id = new_id("ver")
                match = self.execute("SELECT document_id FROM registrations WHERE raw_hash=? AND document_id<>? ORDER BY ingested_at,version_id LIMIT 1", (source.raw_hash, document_id)).fetchone()
                duplicate_of = match[0] if match else None
                previous = document["current_version_id"] if document else None
                sequence = self.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM registrations WHERE document_id=?", (document_id,)).fetchone()[0]
                stored_metadata = metadata.model_copy(update={"title": metadata.title or filename})
                metadata_values = stored_metadata.model_dump()
                metadata_values["title_explicit"] = metadata.title is not None
                if online is not None:
                    metadata_values["online"] = online.model_dump()
                self.execute("""INSERT INTO registrations(version_id,document_id,run_id,raw_hash,doc_type,size_bytes,page_count,status,ingested_at,metadata_json,previous_version_id,duplicate_of,sequence)
                                VALUES (?,?,?,?,?,?,?,'registered',?,?,?,?,?)""",
                             (version_id, document_id, run_id, source.raw_hash, source.doc_type,
                              source.size_bytes, source.page_count, now, json.dumps(metadata_values), previous, duplicate_of, sequence))
                decision = "CHANGED_BYTES_REGISTERED" if previous else "REGISTERED"
                reason = "New byte registration; normalized identity remains undecided."
            self.execute("UPDATE documents SET current_version_id=? WHERE document_id=?", (version_id, document_id))
            state = self.execute("SELECT status,finalized,is_active FROM registrations WHERE version_id=?", (version_id,)).fetchone()
            result = RegistrationResult(document_id=document_id, version_id=version_id, status=state["status"],
                                        finalized=bool(state["finalized"]), is_active=bool(state["is_active"]),
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
                       status=result.status, decision=decision, reason=reason)
        return result

    def fail_attempt(self, attempt_id: str, error: ErrorDetail, *, online: OnlineProvenance | None = None):
        error = error.model_copy(update={"message": safe_text(error.message)})
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            context = json.dumps({"online": online.model_dump()}) if online is not None else None
            self.execute("UPDATE attempts SET status='failed',error_json=?,result_json=? WHERE attempt_id=?", (error.model_dump_json(), context, attempt_id))
            self.execute("UPDATE runs SET failed=failed+1 WHERE run_id=?", (attempt["run_id"],))
            recorded = None
            if attempt["version_id"]:
                status = "extraction_failed" if error.stage == "extraction" else "failed"
                cursor = self.execute("UPDATE registrations SET status=? WHERE version_id=? AND finalized=0 AND status='extracting'",
                                      (status, attempt["version_id"]))
                recorded = status if cursor.rowcount else None
            self.event(run_id=attempt["run_id"], attempt_id=attempt_id,
                       document_id=attempt["document_id"], version_id=attempt["version_id"], status=recorded,
                       decision="PROCESSING_FAILED" if attempt["version_id"] else "REGISTRATION_FAILED",
                       reason=error.message, stage=error.stage, error=error)

    def get_version(self, version_id: str) -> DocumentRecord:
        row = self.execute("""SELECT r.*,d.source_key,d.filename FROM registrations r JOIN documents d USING(document_id)
                              WHERE version_id=?""", (version_id,)).fetchone()
        if row is None:
            raise TechDocQAError("NOT_FOUND", "Registration was not found.", stage="registry")
        return self.document_record(row)

    def begin_processing(self, version_id: str, attempt_id: str):
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            record = self.get_version(version_id)
            current = self.execute("SELECT current_version_id FROM documents WHERE document_id=?", (record.document_id,)).fetchone()[0]
            if not record.finalized and current != version_id:
                raise TechDocQAError("STALE_CANDIDATE", "Only the latest byte candidate can be finalized.", stage="normalization", document_id=record.document_id)
            self.execute("UPDATE attempts SET document_id=?,version_id=? WHERE attempt_id=?", (record.document_id, version_id, attempt_id))
            status = None
            if not record.finalized and not (record.processing and record.processing.resolved_version_id):
                status = "extracting"
                self.execute("UPDATE registrations SET status='extracting' WHERE version_id=?", (version_id,))
            self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=record.document_id,
                       version_id=version_id, status=status, decision="PROCESSING_STARTED", reason="Candidate processing started.", stage="normalization")

    def finalize(self, version_id: str, processing: ProcessingProvenance, attempt_id: str) -> RegistrationResult:
        """Caller verifies immutable artifacts first; lifecycle, outcome and counts commit together."""
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            candidate = self.get_version(version_id)
            if attempt["version_id"] != version_id:
                raise TechDocQAError("INVALID_STATE", "Attempt does not own this candidate.", stage="registry")
            current = self.execute("SELECT current_version_id FROM documents WHERE document_id=?", (candidate.document_id,)).fetchone()[0]
            if not candidate.finalized and current != version_id:
                raise TechDocQAError("STALE_CANDIDATE", "A newer byte candidate exists.", stage="normalization")
            match = self.execute("""SELECT version_id FROM registrations WHERE document_id=? AND content_hash=? AND finalized=1
                                    ORDER BY sequence LIMIT 1""", (candidate.document_id, processing.normalized_hash)).fetchone()
            duplicate = match is not None
            if candidate.finalized and (match is None or match[0] != version_id):
                raise TechDocQAError("SNAPSHOT_MISMATCH", "Finalized content cannot be changed.", stage="storage")
            resolved = match[0] if match else version_id
            if not candidate.finalized:
                if candidate.status not in {"extracting", "normalized"}:
                    raise TechDocQAError("INVALID_STATE", "Candidate is not ready for finalization.", stage="registry")
                values = json.loads(self.execute("SELECT metadata_json FROM registrations WHERE version_id=?", (version_id,)).fetchone()[0])
                values["processing"] = processing.model_copy(update={"resolved_version_id": resolved}).model_dump()
                if candidate.online:
                    values["online"].update(normalized_path=processing.normalized_path, normalized_hash=processing.normalized_hash)
                if processing.original_title and (candidate.title_explicit is False or (
                        candidate.title_explicit is None and candidate.title == candidate.filename)):
                    values["title"] = safe_title(processing.original_title)[:1000]
                if duplicate:
                    self.execute("UPDATE registrations SET status='normalized',metadata_json=? WHERE version_id=?", (json.dumps(values), version_id))
                    if candidate.processing is None and self.reactivate(resolved):
                        self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=candidate.document_id,
                                   version_id=resolved, status=self.get_version(resolved).status, decision="DOCUMENT_REACTIVATED",
                                   reason="Re-ingesting withdrawn content reactivated it.", stage="normalization")
                else:
                    # Only a source still serving this content can own it; superseded history cannot.
                    other = self.content_owner(processing.normalized_hash, candidate.document_id)
                    previous = self.execute("SELECT version_id FROM registrations WHERE document_id=? AND is_active=1", (candidate.document_id,)).fetchone()
                    self.execute("UPDATE registrations SET is_active=0,status='superseded' WHERE document_id=? AND is_active=1", (candidate.document_id,))
                    if previous:
                        self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=candidate.document_id,
                                   version_id=previous[0], status="superseded", decision="VERSION_SUPERSEDED",
                                   reason="A changed normalized version became active.", stage="normalization")
                        self.promote_duplicates(candidate.document_id, processing.normalized_hash, attempt)
                    self.execute("""UPDATE registrations SET status='normalized',finalized=1,is_active=1,content_hash=?,metadata_json=?,duplicate_of=?
                                    WHERE version_id=?""", (processing.normalized_hash, json.dumps(values), other, version_id))
            target = self.get_version(resolved)
            result = RegistrationResult(document_id=target.document_id, version_id=target.version_id, status=target.status,
                deduplicated=duplicate, duplicate_of=target.duplicate_of, run_id=attempt["run_id"],
                finalized=target.finalized, is_active=target.is_active)
            context = result.model_dump()
            if candidate.online:
                context["online"] = candidate.online.model_copy(update={"normalized_path": processing.normalized_path,
                                                                       "normalized_hash": processing.normalized_hash}).model_dump()
            self.execute("UPDATE attempts SET status=?,result_json=? WHERE attempt_id=?",
                         ("skipped" if duplicate else "processed", json.dumps(context), attempt_id))
            self.execute("UPDATE runs SET skipped=skipped+?,processed=processed+? WHERE run_id=?",
                         (int(duplicate), int(not duplicate), attempt["run_id"]))
            self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=candidate.document_id,
                       version_id=version_id, status=target.status, decision="DUPLICATE_SKIPPED" if duplicate else "VERSION_FINALIZED",
                       reason="Normalized content resolves to an existing version; no reactivation." if duplicate else "Validated normalized content finalized atomically.",
                       stage="normalization")
        return result

    def content_owner(self, content_hash: str, document_id: str) -> str | None:
        row = self.execute("""SELECT document_id FROM registrations WHERE content_hash=? AND finalized=1 AND is_active=1
                              AND duplicate_of IS NULL AND document_id<>?
                              ORDER BY ingested_at,version_id LIMIT 1""", (content_hash, document_id)).fetchone()
        return row[0] if row else None

    def reactivate(self, version_id: str) -> bool:
        """Caller holds a transaction and logs the outcome. A newer active version keeps precedence over withdrawn content."""
        row = self.execute("SELECT * FROM registrations WHERE version_id=?", (version_id,)).fetchone()
        if row is None or row["status"] != "withdrawn" or self.active_version(row["document_id"]):
            return False
        status = "chunked" if json.loads(row["metadata_json"]).get("chunking") else "normalized"
        self.execute("UPDATE registrations SET is_active=1,status=?,duplicate_of=? WHERE version_id=?",
                     (status, self.content_owner(row["content_hash"], row["document_id"]), version_id))
        return True

    def promote_duplicates(self, document_id: str, content_hash: str, attempt, *, stage="normalization"):
        """Caller holds a transaction. The earliest copy takes over content its original stopped serving."""
        copies = self.execute("""SELECT version_id,document_id FROM registrations
                                 WHERE duplicate_of=? AND finalized=1 AND is_active=1 AND content_hash<>?
                                 ORDER BY ingested_at,version_id""", (document_id, content_hash)).fetchall()
        if not copies:
            return
        heir = copies[0]
        self.execute("UPDATE registrations SET duplicate_of=NULL WHERE version_id=?", (heir["version_id"],))
        for copy in copies[1:]:
            self.execute("UPDATE registrations SET duplicate_of=? WHERE version_id=?", (heir["document_id"], copy["version_id"]))
        self.event(run_id=attempt["run_id"], attempt_id=attempt["attempt_id"], document_id=heir["document_id"],
                   version_id=heir["version_id"], decision="DUPLICATE_PROMOTED",
                   reason="The original source changed; this copy now serves the content.", stage=stage)

    def begin_chunking(self, version_id: str, attempt_id: str):
        with self.transaction():
            self.pending_attempt(attempt_id)
            record = self.get_version(version_id)
            if not record.finalized or not record.is_active or record.duplicate_of:
                raise TechDocQAError("INVALID_STATE", "Chunking requires an active finalized nonduplicate version.", stage="chunking")
            self.execute("UPDATE attempts SET document_id=?,version_id=? WHERE attempt_id=?",
                         (record.document_id, version_id, attempt_id))

    def save_chunking(self, version_id: str, info: ChunkingProvenance, attempt_id: str, *, skipped=False):
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            record = self.get_version(version_id)
            if attempt['version_id'] != version_id or not record.finalized or not record.is_active or record.duplicate_of:
                raise TechDocQAError("INVALID_STATE", "Chunking target is no longer eligible.", stage="chunking")
            values = json.loads(self.execute("SELECT metadata_json FROM registrations WHERE version_id=?", (version_id,)).fetchone()[0])
            values['chunking'] = info.model_dump()
            status = record.status if skipped else 'chunked'
            self.execute("UPDATE registrations SET metadata_json=?,status=? WHERE version_id=?", (json.dumps(values), status, version_id))
            result = RegistrationResult(document_id=record.document_id, version_id=version_id, status=status,
                deduplicated=skipped, run_id=attempt['run_id'], finalized=True, is_active=True)
            self.execute("UPDATE attempts SET status=?,result_json=? WHERE attempt_id=?",
                         ('skipped' if skipped else 'processed', result.model_dump_json(), attempt_id))
            self.event(run_id=attempt['run_id'], attempt_id=attempt_id, document_id=record.document_id,
                version_id=version_id, status=status, decision='CHUNKING_SKIPPED' if skipped else 'CHUNKS_ACTIVATED',
                reason=f"Verified {info.chunk_count} chunks for configuration {info.chunking_config_id}; "
                       + ('unchanged artifact reused.' if skipped else 'new artifact activated atomically.'), stage='chunking')

    def eligible_versions(self) -> list[DocumentRecord]:
        rows = self.execute(f"""SELECT r.*,d.source_key,d.filename FROM registrations r JOIN documents d USING(document_id)
                                WHERE {ELIGIBLE} AND json_extract(r.metadata_json,'$.chunking') IS NOT NULL
                                ORDER BY r.document_id""").fetchall()
        return [self.document_record(row) for row in rows]

    def active_version(self, document_id: str) -> str | None:
        row = self.execute("SELECT version_id FROM registrations WHERE document_id=? AND is_active=1", (document_id,)).fetchone()
        return row[0] if row else None

    def entity_chunks(self, entity: str, entity_config_id: str) -> set[str]:
        """Verified memberships only where the rows match both the version's current chunk artifact and the active
        entity configuration, so stale rows never filter results (P9-8)."""
        rows = self.execute("""SELECT v.chunk_id FROM verified_entities v JOIN enrichments e USING(version_id)
                               JOIN registrations r USING(version_id)
                               WHERE v.entity=? AND e.entity_config_id=?
                               AND json_extract(r.metadata_json,'$.chunking.snapshot_hash')=e.snapshot_hash
                               AND json_extract(r.metadata_json,'$.chunking.chunking_config_id')=e.chunking_config_id""",
                            (entity.casefold(), entity_config_id)).fetchall()
        return {row[0] for row in rows}

    # Enrichment (Phase 9)

    def enrichment_state(self, version_id: str):
        row = self.execute("SELECT * FROM enrichments WHERE version_id=?", (version_id,)).fetchone()
        return dict(row) if row else None

    def begin_enrichment(self, version_id: str, attempt_id: str) -> DocumentRecord:
        with self.transaction():
            self.pending_attempt(attempt_id)
            record = self.get_version(version_id)
            if not record.finalized or not record.is_active or record.duplicate_of or not record.chunking:
                raise TechDocQAError("INVALID_STATE", "Enrichment requires an active chunked nonduplicate version.",
                                     stage="enrichment", document_id=record.document_id)
            self.execute("UPDATE attempts SET document_id=?,version_id=? WHERE attempt_id=?", (record.document_id, version_id, attempt_id))
        return record

    def save_enrichment(self, version_id: str, attempt_id: str, state: dict, *, entities=(), verified=(), keyphrases=(),
                        categories=(), skipped: bool = False):
        """One transaction per document: old rows go and new rows arrive together, or nothing changes (P9-8)."""
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            record = self.get_version(version_id)
            if (attempt["version_id"] != version_id or not record.finalized or not record.is_active or record.duplicate_of
                    or not record.chunking or record.chunking.snapshot_hash != state["snapshot_hash"]
                    or record.chunking.chunking_config_id != state["chunking_config_id"]):
                raise TechDocQAError("INVALID_STATE", "The version changed during enrichment; rerun enrich.", stage="enrichment",
                                     document_id=record.document_id, retryable=True)
            if not skipped:
                for table in ENRICHMENT_TABLES:
                    self.execute(f"DELETE FROM {table} WHERE version_id=?", (version_id,))
                for row in entities:
                    self.execute("""INSERT INTO entities(version_id,document_id,chunk_id,text,canonical,entity_key,type,source,rule_id,
                                    confidence,verified,chunk_start,chunk_end,document_index,document_start,document_end)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 (version_id, record.document_id, row["chunk_id"], row["text"], row["canonical"], row["entity_key"],
                                  row["type"], row["source"], row["rule_id"], row["confidence"], int(row["verified"]),
                                  row["chunk_start"], row["chunk_end"], row["document_index"], row["document_start"], row["document_end"]))
                for chunk_id, key in sorted(set(verified)):
                    self.execute("INSERT INTO verified_entities(chunk_id,version_id,entity) VALUES (?,?,?)", (chunk_id, version_id, key))
                for scope, rank, phrase, score in keyphrases:
                    self.execute("INSERT INTO keyphrases(version_id,scope,rank,phrase,score) VALUES (?,?,?,?,?)",
                                 (version_id, scope, rank, phrase, score))
                for row in categories:
                    self.execute("INSERT INTO document_categories(version_id,rank,category,confidence,assigned,source) VALUES (?,?,?,?,?,?)",
                                 (version_id, row["rank"], row["category"], row["confidence"], int(row["assigned"]), "embedding"))
                self.execute("""INSERT INTO enrichments(version_id,chunking_config_id,snapshot_hash,enrichment_config_id,entity_config_id,
                                keyphrase_config_id,classifier_config_id,entity_count,verified_count,keyphrase_status,classification_status,
                                run_id,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (version_id, state["chunking_config_id"], state["snapshot_hash"], state["enrichment_config_id"],
                              state["entity_config_id"], state["keyphrase_config_id"], state["classifier_config_id"], len(entities),
                              sum(1 for row in entities if row["verified"]), state["keyphrase_status"], state["classification_status"],
                              attempt["run_id"], utc_now()))
            result = RegistrationResult(document_id=record.document_id, version_id=version_id, status=record.status,
                                        deduplicated=skipped, run_id=attempt["run_id"], finalized=True, is_active=True)
            self.execute("UPDATE attempts SET status=?,result_json=? WHERE attempt_id=?",
                         ("skipped" if skipped else "processed", result.model_dump_json(), attempt_id))
            current = self.enrichment_state(version_id)
            self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=record.document_id, version_id=version_id,
                       decision="ENRICHMENT_SKIPPED" if skipped else "ENRICHMENT_SAVED", stage="enrichment",
                       reason=(f"Enrichment {current['enrichment_config_id']} already current." if skipped else
                               f"{current['entity_count']} entities ({current['verified_count']} verified), keyphrases "
                               f"{current['keyphrase_status']}, classification {current['classification_status']}."))

    def category_vector(self, key: str) -> bytes | None:
        row = self.execute("SELECT vector FROM category_embeddings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def save_category_vector(self, key: str, profile_id: str, vector: bytes):
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO category_embeddings(key,profile_id,vector,created_at) VALUES (?,?,?,?)",
                         (key, profile_id, vector, utc_now()))

    def chunk_vectors(self, version_id: str, profile_id: str, chunking_config_id: str) -> list[bytes] | None:
        """One stored vector per current chunk occurrence, or None while any chunk lacks one.

        A chunk with no row at all (an index run interrupted between batches) counts as missing: the row count must equal
        the chunk artifact's chunk_count.
        """
        record = self.get_version(version_id)
        if not record.chunking or record.chunking.chunking_config_id != chunking_config_id:
            return None
        rows = self.execute("""SELECT c.status,e.vector FROM chunk_embeddings c LEFT JOIN embeddings e USING(chunk_key)
                               WHERE c.version_id=? AND c.profile_id=? AND c.chunking_config_id=? ORDER BY c.chunk_id""",
                            (version_id, profile_id, chunking_config_id)).fetchall()
        if len(rows) != record.chunking.chunk_count or any(row[0] != "embedded" or row[1] is None for row in rows):
            return None
        return [row[1] for row in rows]

    def version_entities(self, version_id: str, chunk_id: str | None = None) -> list[dict]:
        rows = self.execute("""SELECT chunk_id,text,canonical,type,source,rule_id,confidence,verified,chunk_start,chunk_end,
                               document_index,document_start,document_end FROM entities
                               WHERE version_id=? AND (? IS NULL OR chunk_id=?) ORDER BY entity_id""",
                            (version_id, chunk_id, chunk_id)).fetchall()
        return [{**dict(row), "verified": bool(row["verified"])} for row in rows]

    def version_keyphrases(self, version_id: str) -> dict[str, list[dict]]:
        found = {}
        for row in self.execute("SELECT scope,rank,phrase,score FROM keyphrases WHERE version_id=? ORDER BY scope,rank", (version_id,)).fetchall():
            found.setdefault(row["scope"], []).append({"rank": row["rank"], "phrase": row["phrase"], "score": row["score"]})
        return found

    def version_categories(self, version_id: str) -> list[dict]:
        rows = self.execute("SELECT rank,category,confidence,assigned,source FROM document_categories WHERE version_id=? ORDER BY rank",
                            (version_id,)).fetchall()
        return [{**dict(row), "assigned": bool(row["assigned"])} for row in rows]

    def inferred_categories(self, classifier_config_id: str) -> dict[str, set[str]]:
        """Assigned inferred categories per version, only where the rows match both the version's current chunk
        artifact and the active classifier; 'unclassified' is a value of its own (P9-7)."""
        rows = self.execute("""SELECT e.version_id,e.classification_status,c.category,c.assigned FROM enrichments e
                               JOIN registrations r USING(version_id) LEFT JOIN document_categories c USING(version_id)
                               WHERE e.classifier_config_id=?
                               AND json_extract(r.metadata_json,'$.chunking.snapshot_hash')=e.snapshot_hash""",
                            (classifier_config_id,)).fetchall()
        found = {}
        for row in rows:
            values = found.setdefault(row["version_id"], set())
            if row["classification_status"] == "unclassified":
                values.add("unclassified")
            elif row["assigned"]:
                values.add(row["category"].casefold())
        return found

    def deleted_document_ids(self) -> set[str]:
        """The anonymous audit event is all that names a deleted document; its reason starts with the ID."""
        rows = self.execute("SELECT reason FROM events WHERE decision='DOCUMENT_DELETED'").fetchall()
        return {row[0].split(":", 1)[0] for row in rows if row[0]}

    def save_embedding_profile(self, profile: dict):
        with self.transaction():
            self.execute("""INSERT OR IGNORE INTO embedding_profiles(profile_id,provider,embedding_model_id,dimension,normalization,metric,collection,created_at)
                            VALUES (?,?,?,?,?,?,?,?)""", (profile["profile_id"], profile["provider"], profile["embedding_model_id"], profile["dimension"],
                                                         profile["normalization"], profile["metric"], profile["collection"], utc_now()))

    def stored_keys(self, profile_id: str, keys: list[str]) -> set[str]:
        found = set()
        for start in range(0, len(keys), SQL_BATCH):
            batch = keys[start:start + SQL_BATCH]
            marks = ",".join("?" * len(batch))
            found.update(row[0] for row in self.execute(f"SELECT chunk_key FROM embeddings WHERE profile_id=? AND chunk_key IN ({marks})", (profile_id, *batch)).fetchall())
        return found

    def load_vectors(self, keys: list[str]) -> dict[str, bytes]:
        vectors = {}
        unique = list(dict.fromkeys(keys))
        for start in range(0, len(unique), SQL_BATCH):
            batch = unique[start:start + SQL_BATCH]
            marks = ",".join("?" * len(batch))
            vectors.update((row[0], row[1]) for row in self.execute(f"SELECT chunk_key,vector FROM embeddings WHERE chunk_key IN ({marks})", batch).fetchall())
        return vectors

    def record_embeddings(self, version_id: str, profile_id: str, rows: list[dict]):
        """One outcome per chunk occurrence; several occurrences can share one stored vector."""
        now = utc_now()
        with self.transaction():
            for row in rows:
                chunk = row["chunk"]
                if row["vector"] is not None:
                    self.execute("INSERT OR IGNORE INTO embeddings(chunk_key,profile_id,text_hash,vector,created_at) VALUES (?,?,?,?,?)",
                                 (row["key"], profile_id, chunk["text_hash"], row["vector"], now))
                self.execute("""INSERT OR REPLACE INTO chunk_embeddings(chunk_id,profile_id,version_id,chunk_key,chunking_config_id,status,reason,updated_at)
                                VALUES (?,?,?,?,?,?,?,?)""", (chunk["chunk_id"], profile_id, version_id, row["key"], chunk["chunking_config_id"],
                                                             "embedding_failed" if row["reason"] else "embedded", row["reason"], now))

    def text_embedded_elsewhere(self, profile_id: str, text_hashes: set[str]) -> bool:
        items = list(text_hashes)
        for start in range(0, len(items), SQL_BATCH):
            batch = items[start:start + SQL_BATCH]
            marks = ",".join("?" * len(batch))
            if self.execute(f"SELECT 1 FROM embeddings WHERE profile_id<>? AND text_hash IN ({marks}) LIMIT 1", (profile_id, *batch)).fetchone():
                return True
        return False

    def document_embedded_before(self, record, profile_id: str) -> bool:
        return self.execute("""SELECT 1 FROM chunk_embeddings c JOIN registrations r USING(version_id)
                               WHERE r.document_id=? AND c.version_id<>? AND c.profile_id=? AND c.status='embedded' LIMIT 1""",
                            (record.document_id, record.version_id, profile_id)).fetchone() is not None

    def indexed_chunk_ids(self, profile_id: str) -> set[str]:
        rows = self.execute(f"""SELECT c.chunk_id FROM chunk_embeddings c JOIN registrations r USING(version_id)
                                WHERE c.profile_id=? AND c.status='embedded' AND r.status='indexed' AND {ELIGIBLE}
                                AND json_extract(r.metadata_json,'$.chunking.chunking_config_id')=c.chunking_config_id""", (profile_id,)).fetchall()
        return {row[0] for row in rows}

    def indexable(self, version_id: str) -> DocumentRecord:
        record = self.get_version(version_id)
        if not record.finalized or not record.is_active or record.duplicate_of or not record.chunking:
            raise TechDocQAError("INVALID_STATE", "Indexing requires an active chunked nonduplicate version.", stage="indexing", document_id=record.document_id)
        return record

    def begin_indexing(self, version_id: str, attempt_id: str) -> DocumentRecord:
        with self.transaction():
            self.pending_attempt(attempt_id)
            record = self.indexable(version_id)
            self.execute("UPDATE attempts SET document_id=?,version_id=? WHERE attempt_id=?", (record.document_id, version_id, attempt_id))
        return record

    def log_embedding(self, record, attempt_id: str, decision: str, reason: str):
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=record.document_id, version_id=record.version_id,
                       decision=decision, reason=reason, stage="embedding")

    def set_index_status(self, version_id: str, status: str, attempt_id: str):
        """Records embedded; an already indexed version stays searchable during a rerun."""
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            record = self.indexable(version_id)
            if record.status == "chunked":
                self.execute("UPDATE registrations SET status=? WHERE version_id=?", (status, version_id))
                self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=record.document_id, version_id=version_id,
                           status=status, decision="CHUNKS_EMBEDDED", reason="Every chunk has one valid stored embedding.", stage="embedding")

    def complete_indexing(self, version_id: str, attempt_id: str, *, skipped: bool, entries: int):
        with self.transaction():
            attempt = self.pending_attempt(attempt_id)
            record = self.indexable(version_id)
            self.execute("UPDATE registrations SET status='indexed' WHERE version_id=?", (version_id,))
            result = RegistrationResult(document_id=record.document_id, version_id=version_id, status="indexed",
                deduplicated=skipped, run_id=attempt["run_id"], finalized=True, is_active=True)
            self.execute("UPDATE attempts SET status=?,result_json=? WHERE attempt_id=?",
                         ("skipped" if skipped else "processed", result.model_dump_json(), attempt_id))
            self.event(run_id=attempt["run_id"], attempt_id=attempt_id, document_id=record.document_id, version_id=version_id, status="indexed",
                       decision="INDEX_SKIPPED" if skipped else "VERSION_INDEXED",
                       reason="Index entries already current." if skipped else f"{entries} vector entries written.", stage="indexing")

    def withdraw(self, document_id: str, reason: str) -> str:
        """Takes effect for search as this transaction commits, whatever the derived indexes still hold."""
        with self.transaction():
            self.get_document(document_id)
            version_id = self.active_version(document_id)
            if version_id is None:
                raise TechDocQAError("NO_ACTIVE_VERSION", "This document has no active version to withdraw.", stage="lifecycle", document_id=document_id)
            self.execute("UPDATE registrations SET is_active=0,status='withdrawn' WHERE version_id=?", (version_id,))
            self.promote_duplicates(document_id, "", {"run_id": None, "attempt_id": None}, stage="lifecycle")
            self.event(document_id=document_id, version_id=version_id, status="withdrawn",
                       decision="DOCUMENT_WITHDRAWN", reason=safe_text(reason), stage="lifecycle")
        return version_id

    def document_collections(self, document_id: str) -> list[str]:
        rows = self.execute("""SELECT DISTINCT p.collection FROM chunk_embeddings c JOIN embedding_profiles p USING(profile_id)
                               JOIN registrations r USING(version_id) WHERE r.document_id=? ORDER BY p.collection""", (document_id,)).fetchall()
        return [row[0] for row in rows]

    def registered_files(self, where: str, parameters=()) -> set[str]:
        files = set()
        for row in self.execute(f"SELECT raw_hash,doc_type,metadata_json FROM registrations WHERE {where}", parameters).fetchall():
            files |= artifact_paths(json.loads(row["metadata_json"])) | {f"local/snapshots/{row['raw_hash']}.{row['doc_type']}"}
        for row in self.execute(f"SELECT result_json FROM attempts WHERE result_json IS NOT NULL AND {where}", parameters).fetchall():
            files |= artifact_paths(json.loads(row[0]))
        return files

    def document_files(self, document_id: str) -> set[str]:
        return self.registered_files("document_id=?", (document_id,))

    def all_files(self) -> set[str]:
        return self.registered_files("1=1")

    def delete_document(self, document_id: str, reason: str):
        """Keeps run counts and one anonymous audit event; everything naming the document goes."""
        with self.transaction():
            self.get_document(document_id)
            versions = "SELECT version_id FROM registrations WHERE document_id=?"
            keys = [row[0] for row in self.execute(f"SELECT DISTINCT chunk_key FROM chunk_embeddings WHERE version_id IN ({versions})", (document_id,)).fetchall()]
            for table in ENRICHMENT_TABLES:
                self.execute(f"DELETE FROM {table} WHERE version_id IN ({versions})", (document_id,))
            self.execute(f"DELETE FROM chunk_embeddings WHERE version_id IN ({versions})", (document_id,))
            for start in range(0, len(keys), SQL_BATCH):
                batch = keys[start:start + SQL_BATCH]
                marks = ",".join("?" * len(batch))
                # A vector stays while another source's identical chunk still uses it.
                self.execute(f"""DELETE FROM embeddings WHERE chunk_key IN ({marks})
                                 AND chunk_key NOT IN (SELECT chunk_key FROM chunk_embeddings WHERE chunk_key IN ({marks}))""", (*batch, *batch))
            self.execute(f"DELETE FROM events WHERE document_id=? OR version_id IN ({versions})", (document_id, document_id))
            self.execute(f"""UPDATE attempts SET document_id=NULL,version_id=NULL,result_json=NULL
                             WHERE document_id=? OR version_id IN ({versions})""", (document_id, document_id))
            self.execute("UPDATE registrations SET duplicate_of=NULL WHERE duplicate_of=?", (document_id,))
            self.execute("UPDATE documents SET current_version_id=NULL WHERE document_id=?", (document_id,))
            self.execute("DELETE FROM registrations WHERE document_id=?", (document_id,))
            self.execute("DELETE FROM documents WHERE document_id=?", (document_id,))
            self.event(decision="DOCUMENT_DELETED", reason=f"{document_id}: {safe_text(reason)}", stage="lifecycle")

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
            stage = self.get_run(run[0]).run.stage
            attempts = self.execute("SELECT attempt_id FROM attempts WHERE run_id=? AND status='pending' ORDER BY input_index", (run[0],)).fetchall()
            for attempt in attempts:
                error = TechDocQAError("RUN_INTERRUPTED", "Processing was interrupted; rerun the requested stage.",
                                       stage=stage, retryable=True).response.error
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
        processing = self.execute("SELECT stage FROM events WHERE run_id=? AND decision IN ('PROCESSING_RUN_STARTED','CHUNKING_RUN_STARTED','INDEXING_RUN_STARTED','ENRICHMENT_RUN_STARTED') LIMIT 1", (run_id,)).fetchone()
        return BatchResult(run=RunSummary(**dict(row), stage=processing[0] if processing else "registration"), outcomes=outcomes)

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
