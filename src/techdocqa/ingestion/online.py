"""Catalog selection, isolated processing, snapshots and existing registry coordination."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.safety import ValidatedSource
from techdocqa.ingestion.urls import canonical_url
from techdocqa.registry import Registry, new_id
from techdocqa.schemas import BatchResult, ErrorDetail, OnlineProvenance, RegistrationMetadata
from techdocqa.settings import OnlineSource, Settings


def select_pages(source_ids: list[str], urls: list[str], settings: Settings) -> list[tuple]:
    pages = []
    for source_id in source_ids:
        source = next((item for item in settings.online.sources if item.source_id == source_id and item.enabled), None)
        if source is None:
            pages.append((None, None, TechDocQAError("SOURCE_NOT_APPROVED", "Source is unknown or disabled.", stage="arguments")))
        else:
            pages.extend((source, url, None) for url in source.pages)
    for value in urls:
        try:
            url = canonical_url(value)
            source = next((item for item in settings.online.sources if item.enabled
                           and url in {item.entry_url, *item.pages}), None)
            if source is None:
                raise ValueError
            pages.append((source, url, None))
        except ValueError:
            error = TechDocQAError("URL_NOT_ALLOWED", "URL is not an explicitly approved HTTPS page.", stage="fetch")
            pages.append((None, None, error))
    if not pages or len(pages) > settings.online.max_pages_per_run:
        raise TechDocQAError("INVALID_ARGUMENT", "Select a bounded nonempty list of approved pages.", stage="arguments")
    return pages


def run_page_worker(source: OnlineSource, url: str, settings: Settings, directory: Path) -> dict:
    request = {"source": source.model_dump(), "url": url, "policy": settings.online.model_dump(),
               "max_bytes": settings.ingestion.max_file_bytes, "minimum": settings.ingestion.min_text_characters,
               "directory": str(directory)}
    try:
        completed = subprocess.run([sys.executable, "-I", "-m", "techdocqa.ingestion.online_worker"],
                                   input=json.dumps(request).encode(), capture_output=True,
                                   timeout=settings.ingestion.parse_timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        raise TechDocQAError("PAGE_TIMEOUT", "Documentation fetch/extraction exceeded its overall deadline.", stage="ingestion", retryable=True) from None
    except OSError:
        raise TechDocQAError("PAGE_WORKER_FAILED", "Documentation worker could not start.", stage="ingestion", retryable=True) from None
    try:
        output = json.loads(completed.stdout)
        if completed.returncode or not isinstance(output, dict):
            raise ValueError
        return output
    except (ValueError, TypeError):
        raise TechDocQAError("PAGE_WORKER_FAILED", "Documentation worker returned an invalid response.", stage="ingestion", retryable=True) from None


def store_snapshot(root: Path, kind: str, data: bytes, suffix: str) -> tuple[Path, str]:
    digest = hashlib.sha256(data).hexdigest()
    directory = root / "online" / kind
    if not directory.resolve().is_relative_to(root):
        raise TechDocQAError("UNSAFE_STORAGE", "Snapshot storage escapes the configured data directory.", stage="storage")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest + suffix)
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise TechDocQAError("UNSAFE_STORAGE", "Snapshot storage is unsafe.", stage="storage")
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        # Publish complete bytes without replacing an existing immutable snapshot.
        try:
            os.link(temporary, path)
        except FileExistsError:
            with path.open("rb") as handle:
                if handle.read(len(data) + 1) != data:
                    raise TechDocQAError("SNAPSHOT_MISMATCH", "Existing snapshot failed its integrity check.", stage="storage") from None
    finally:
        temporary.unlink(missing_ok=True)
    return path, digest


def export_manifest(registry: Registry, root: Path) -> str:
    documents = []
    rows = registry.execute("""SELECT r.*,d.source_key,d.filename FROM registrations r
                               JOIN documents d USING(document_id) ORDER BY d.source_key,r.sequence""").fetchall()
    for row in rows:
        record = registry.document_record(row)
        if record.online is not None:
            documents.append({**record.model_dump(), "format": "html", "relative_local_path": record.online.snapshot_path})
    retrievals = []
    for row in registry.execute("SELECT run_id,attempt_id,input_index,status,result_json,error_json FROM attempts ORDER BY rowid").fetchall():
        result = json.loads(row["result_json"]) if row["result_json"] else {}
        if "online" in result:
            retrievals.append({"run_id": row["run_id"], "attempt_id": row["attempt_id"], "input_index": row["input_index"],
                               "status": row["status"], "online": result["online"],
                               "error": json.loads(row["error_json"]) if row["error_json"] else None})
    manifest = {"schema_version": 1, "status": "draft", "dataset_id": None,
                "technologies": sorted({record["technology"] for record in documents if record["technology"]}),
                "documents": documents, "retrievals": retrievals,
                "purpose": "unfrozen_online_candidates"}
    directory = root / "online"
    if not directory.resolve().is_relative_to(root):
        raise TechDocQAError("UNSAFE_STORAGE", "Manifest storage is unsafe.", stage="storage")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "corpus_manifest.json"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(manifest, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.relative_to(root).as_posix()


class OnlineBatchResult(BatchResult):
    pages_attempted: int
    pages_succeeded: int
    pages_failed: int
    manifest_path: str | None = None
    warnings: list[str]


def ingest_online(source_ids: list[str], urls: list[str], settings: Settings, registry: Registry,
                  *, metadata: RegistrationMetadata | None = None) -> OnlineBatchResult:
    pages = select_pages(source_ids, urls, settings)
    metadata = metadata or RegistrationMetadata()
    root = Path(settings.data_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with registry.registration_lock():
        registry.recover_interrupted_runs()
        run_id, attempts = registry.start_run(len(pages))
        for index, ((source, url, preflight_error), attempt_id) in enumerate(zip(pages, attempts, strict=True)):
            provenance = None
            try:
                if preflight_error is not None:
                    raise preflight_error
                provenance = OnlineProvenance(source_id=source.source_id, canonical_url=url,
                                              usage_policy_url=source.usage_policy_url, usage_status=source.usage_status,
                                              configuration_id=hashlib.sha256(json.dumps({
                                                  "source": source.model_dump(), "network": settings.online.model_dump(exclude={"sources"}),
                                                  "ingestion": settings.ingestion.model_dump(),
                                              }, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
                if index:
                    time.sleep(settings.online.request_interval_seconds)
                with tempfile.TemporaryDirectory(prefix="online-", dir=root) as working:
                    directory = Path(working)
                    output = run_page_worker(source, url, settings, directory)
                    raw_path = directory / "page.html"
                    if raw_path.exists():
                        with raw_path.open("rb") as handle:
                            raw = handle.read(settings.ingestion.max_file_bytes + 1)
                        if len(raw) > settings.ingestion.max_file_bytes:
                            raise TechDocQAError("FILE_TOO_LARGE", "Snapshot exceeds the configured byte limit.", stage="storage")
                        snapshot, raw_hash = store_snapshot(root, "snapshots", raw, ".html")
                        provenance = provenance.model_copy(update={
                            "final_url": output["final_url"], "retrieval_id": new_id("fetch"),
                            "retrieved_at": output["retrieved_at"], "content_type": output["content_type"],
                            "content_type_header": output["content_type_header"],
                            "snapshot_id": raw_hash, "snapshot_path": snapshot.relative_to(root).as_posix(),
                            "size_bytes": len(raw), "http_status": 200,
                            "etag": output.get("etag"), "last_modified": output.get("last_modified"),
                        })
                    if "error" in output:
                        error = ErrorDetail.model_validate(output["error"])
                        if provenance.snapshot_id is not None:
                            provenance.extraction_status = "extraction_failed"
                        raise TechDocQAError(error.code, error.message, stage=error.stage, retryable=error.retryable)
                    extracted = (directory / "extracted.txt").read_bytes()
                    extracted_path, extracted_hash = store_snapshot(root, "extracted", extracted, ".txt")
                    if extracted_hash != output["extracted_hash"]:
                        raise TechDocQAError("SNAPSHOT_MISMATCH", "Extraction integrity check failed.", stage="storage")
                    provenance = provenance.model_copy(update={
                        "original_title": output["original_title"], "encoding": output["encoding"],
                        "headings": output["headings"], "warnings": output["warnings"],
                        "code_spans": output["code_spans"], "extraction_dependencies": output["extraction_dependencies"],
                        "extraction_policy": output["extraction_policy"], "extraction_status": "extracted",
                        "extracted_path": extracted_path.relative_to(root).as_posix(), "extracted_hash": extracted_hash,
                    })
                    page_metadata = RegistrationMetadata.model_validate({**metadata.model_dump(),
                        "technology": source.technology, "source_url": url,
                        "title": metadata.title or provenance.original_title or source.title,
                    })
                    registry.register(ValidatedSource(snapshot, raw_hash, "html", len(raw)), page_metadata,
                                      None, attempt_id, online=provenance)
            except TechDocQAError as error:
                registry.fail_attempt(attempt_id, error.response.error, online=provenance)
            except (OSError, ValueError, KeyError, TypeError):
                error = TechDocQAError("ONLINE_INGESTION_FAILED", "Online ingestion failed safely.", stage="ingestion")
                registry.fail_attempt(attempt_id, error.response.error, online=provenance)
        registry.finish_run(run_id)
        result = registry.get_run(run_id)
        warnings = []
        manifest_path = None
        try:
            manifest_path = export_manifest(registry, root)
        except (TechDocQAError, OSError):
            warnings.append("MANIFEST_EXPORT_FAILED")
        return OnlineBatchResult(**result.model_dump(), pages_attempted=len(pages),
                                 pages_succeeded=result.run.processed + result.run.skipped,
                                 pages_failed=result.run.failed, manifest_path=manifest_path, warnings=warnings)
