"""Verified snapshots -> offline worker -> atomic normalized-version finalization."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unicodedata

from langchain_core.documents import Document
from pydantic import Field

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.online import export_manifest, store_snapshot
from techdocqa.ingestion.safety import validate_file
from techdocqa.normalization import NORMALIZATION_POLICY, document_text
from techdocqa.registry import Registry
from techdocqa.schemas import BatchResult, ErrorDetail, ProcessingProvenance
from techdocqa.settings import Settings


class ProcessingBatchResult(BatchResult):
    warnings: list[str] = Field(default_factory=list)
    manifest_path: str | None = None


def verify_processing(record, info: ProcessingProvenance, settings: Settings) -> list[Document]:
    root = Path(settings.data_directory).resolve()
    limit = settings.ingestion.max_file_bytes
    read_snapshot(root, info.snapshot_path, record.raw_hash, limit)
    read_snapshot(root, info.extracted_path, info.extracted_hash, limit * 8)
    text = read_snapshot(root, info.normalized_path, info.normalized_hash, limit * 8)
    data = read_snapshot(root, info.documents_path, info.documents_hash, limit * 8)
    documents = [Document(**item) for item in json.loads(data)]
    if not documents or sum(not char.isspace() for doc in documents for char in doc.page_content) < settings.ingestion.min_text_characters:
        raise TechDocQAError("NO_TEXT_EXTRACTED", "Normalized documents contain too little usable text.", stage="normalization")
    if document_text(documents).encode("utf-8") != text:
        raise TechDocQAError("SNAPSHOT_MISMATCH", "Normalized documents disagree with their text hash.", stage="storage")
    return documents


def read_snapshot(root: Path, relative: str, digest: str, limit: int) -> bytes:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root) or path.is_symlink():
        raise TechDocQAError("UNSAFE_STORAGE", "Snapshot path is unsafe.", stage="storage")
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        raise TechDocQAError("SNAPSHOT_NOT_ACCESSIBLE", "Required snapshot is unavailable.", stage="storage", retryable=True) from None
    if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
        raise TechDocQAError("SNAPSHOT_MISMATCH", "Snapshot integrity check failed.", stage="storage")
    return data


def run_processing_worker(request: dict, settings: Settings) -> dict:
    stage = "chunking" if request.get("chunking") else "extraction"
    try:
        completed = subprocess.run([sys.executable, "-I", "-m", "techdocqa.ingestion.processing_worker"],
            input=json.dumps(request).encode("utf-8"), capture_output=True,
            timeout=settings.ingestion.parse_timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        raise TechDocQAError("PARSE_TIMEOUT", "Document processing exceeded its deadline.", stage=stage, retryable=True) from None
    except OSError:
        raise TechDocQAError("PROCESSING_WORKER_FAILED", "Processing worker could not start.", stage=stage, retryable=True) from None
    try:
        output = json.loads(completed.stdout)
        if completed.returncode or not isinstance(output, dict):
            raise ValueError
        if "error" in output:
            detail = ErrorDetail.model_validate(output["error"])
            raise TechDocQAError(detail.code, detail.message, stage=detail.stage, retryable=detail.retryable)
        return output
    except (ValueError, TypeError):
        raise TechDocQAError("PROCESSING_WORKER_FAILED", "Processing worker returned an invalid response.", stage=stage, retryable=True) from None


def prepare_candidate(record, settings: Settings, registry: Registry, directory: Path) -> ProcessingProvenance:
    root = Path(settings.data_directory).resolve()
    limit = settings.ingestion.max_file_bytes
    if record.processing:
        info = record.processing
        verify_processing(record, info, settings)
        return info
    request = {"directory": str(directory), "doc_type": record.doc_type, "minimum": settings.ingestion.min_text_characters}
    if record.online:
        provenance = record.online
        snapshot_path = provenance.snapshot_path
        if provenance.snapshot_id != record.raw_hash or provenance.extraction_status != "extracted":
            raise TechDocQAError("SNAPSHOT_MISMATCH", "Online extraction provenance is inconsistent.", stage="storage")
        read_snapshot(root, snapshot_path, record.raw_hash, limit)
        extracted = read_snapshot(root, provenance.extracted_path, provenance.extracted_hash, limit * 8).decode("utf-8")
        metadata = {"doc_type": "html", "code_spans": provenance.code_spans, "headings": provenance.headings,
                    "original_title": provenance.original_title, "encoding": provenance.encoding,
                    "extraction_dependencies": provenance.extraction_dependencies, "extraction_policy": provenance.extraction_policy}
        (directory / "input.json").write_text(json.dumps([{"page_content": extracted, "metadata": metadata}], ensure_ascii=True), encoding="utf-8")
        request["extracted"] = True
    else:
        snapshot_path = f"local/snapshots/{record.raw_hash}.{record.doc_type}"
        if (root / snapshot_path).exists():
            read_snapshot(root, snapshot_path, record.raw_hash, limit)
        else:
            source_path = registry.execute("SELECT source_path FROM documents WHERE document_id=?", (record.document_id,)).fetchone()[0]
            source = validate_file(Path(source_path), settings, capture=True)
            if source.raw_hash != record.raw_hash:
                raise TechDocQAError("SOURCE_CHANGED", "Local bytes no longer match the registration; register the changed input.", stage="extraction", retryable=True)
            snapshot, _ = store_snapshot(root, "snapshots", source.data, "." + record.doc_type, namespace="local")
            snapshot_path = snapshot.relative_to(root).as_posix()
        request["snapshot"] = str(root / snapshot_path)
    output = run_processing_worker(request, settings)
    stored = {}
    for name, kind, suffix in (("extracted", "extracted", ".json"), ("normalized", "normalized", ".txt"), ("documents", "documents", ".json")):
        working = directory / ("normalized.json" if name == "documents" else name + suffix)
        with working.open("rb") as handle:
            data = handle.read(limit * 8 + 1)
        if len(data) > limit * 8:
            raise TechDocQAError("TEXT_TOO_LARGE", "Processed text exceeds the bounded storage limit.", stage="normalization")
        path, digest = store_snapshot(root, kind, data, suffix, namespace="processing")
        stored[name + "_path"] = path.relative_to(root).as_posix()
        stored[name + "_hash"] = digest
    info = ProcessingProvenance(snapshot_path=snapshot_path, **stored,
        normalization_policy=NORMALIZATION_POLICY, unicode_version=unicodedata.unidata_version,
        original_title=output.get("original_title"), encoding=output.get("encoding"),
        extraction_dependencies=output.get("extraction_dependencies") or {})
    verify_processing(record, info, settings)
    return info


def process_versions(version_ids: list[str], settings: Settings, registry: Registry) -> ProcessingBatchResult:
    root = Path(settings.data_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with registry.registration_lock():
        registry.recover_interrupted_runs()
        if not version_ids:
            version_ids = [record.version_id for record in registry.list_documents()]
        if not version_ids:
            raise TechDocQAError("INVALID_ARGUMENT", "No registered candidates are available.", stage="arguments")
        run_id, attempts = registry.start_run(len(version_ids), stage="normalization")
        for version_id, attempt_id in zip(version_ids, attempts, strict=True):
            record = None
            try:
                registry.begin_processing(version_id, attempt_id)
                record = registry.get_version(version_id)
                with tempfile.TemporaryDirectory(prefix="processing-", dir=root) as working:
                    info = prepare_candidate(record, settings, registry, Path(working))
                registry.finalize(version_id, info, attempt_id)
            except TechDocQAError as error:
                detail = error.response.error.model_copy(update={"document_id": record.document_id if record else error.response.error.document_id})
                registry.fail_attempt(attempt_id, detail, online=record.online if record else None)
            except (OSError, ValueError, TypeError, KeyError):
                error = TechDocQAError("PROCESSING_FAILED", "Candidate processing failed safely.", stage="normalization",
                                       document_id=record.document_id if record else None)
                registry.fail_attempt(attempt_id, error.response.error, online=record.online if record else None)
        registry.finish_run(run_id)
        warnings, manifest_path = [], None
        if any(record.online for record in registry.list_documents()):
            try:
                manifest_path = export_manifest(registry, root)
            except (TechDocQAError, OSError):
                warnings.append("MANIFEST_EXPORT_FAILED")
        return ProcessingBatchResult(**registry.get_run(run_id).model_dump(), warnings=warnings, manifest_path=manifest_path)


def finalized_documents(version_id: str, settings: Settings, registry: Registry) -> list[Document]:
    """Future consumers use the resolved version and registry-owned citation metadata."""
    record = registry.get_version(version_id)
    if not record.finalized or record.processing is None:
        raise TechDocQAError("INVALID_STATE", "A finalized version is required.", stage="registry")
    info = record.processing
    documents = verify_processing(record, info, settings)
    if hashlib.sha256(document_text(documents).encode("utf-8")).hexdigest() != record.content_hash:
        raise TechDocQAError("SNAPSHOT_MISMATCH", "Finalized content failed verification.", stage="storage")
    metadata = record.model_dump(exclude={"processing"})
    return [Document(page_content=doc.page_content, metadata={**doc.metadata, **metadata}) for doc in documents]
