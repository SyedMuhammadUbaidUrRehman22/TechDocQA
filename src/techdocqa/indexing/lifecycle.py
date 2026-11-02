"""Withdrawal and permanent deletion across the registry, vector store and stored files (FR-21)."""

import json
from pathlib import Path

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.online import export_manifest
from techdocqa.privacy import safe_text
from techdocqa.schemas import LifecycleResult


def checked_reason(reason: str) -> str:
    reason = safe_text(reason)
    if not reason:
        raise TechDocQAError("INVALID_ARGUMENT", "A reason is required.", stage="arguments")
    return reason


def withdraw_document(document_id: str, reason: str, registry) -> LifecycleResult:
    """Registry only: search leaves immediately, and the next index run removes the vector entries."""
    reason = checked_reason(reason)
    version_id = registry.withdraw(document_id, reason)
    return LifecycleResult(document_id=document_id, status="withdrawn", reason=reason, version_id=version_id)


def old_chunk_artifacts(root: Path, document_id: str) -> list[str]:
    """Replaced chunk artifacts have no registry pointer, but each names its own document."""
    found = []
    directory = root / "chunking" / "artifacts"
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        chunks = json.loads(path.read_bytes()).get("chunks") or [{}]
        if chunks[0].get("document_id") == document_id:
            found.append(path.relative_to(root).as_posix())
    return found


def delete_document(document_id: str, reason: str, settings, registry) -> LifecycleResult:
    from techdocqa.indexing.vector_store import VectorStore
    reason = checked_reason(reason)
    root = Path(settings.data_directory).resolve()
    with registry.registration_lock():
        record = registry.get_document(document_id)
        if registry.active_version(document_id):
            # Out of search first, so a failure below leaves it withdrawn and the delete can be retried.
            registry.withdraw(document_id, reason)
        removed = 0
        for collection in registry.document_collections(document_id):
            store = VectorStore(settings.data_directory, collection)
            removed += store.delete(store.ids(where={"document_id": document_id}))
        files = registry.document_files(document_id) | set(old_chunk_artifacts(root, document_id))
        registry.delete_document(document_id, reason)
        kept = registry.all_files()
        removed_files, warnings = 0, []
        for relative in sorted(files - kept):
            path = root / relative
            if not path.resolve().is_relative_to(root):
                continue
            try:
                if path.exists():
                    path.unlink()
                    removed_files += 1
            except OSError:
                warnings.append("FILE_NOT_REMOVED")
        if record.online:
            try:
                export_manifest(registry, root)
            except (TechDocQAError, OSError):
                warnings.append("MANIFEST_EXPORT_FAILED")
    return LifecycleResult(document_id=document_id, status="deleted", reason=reason, removed_entries=removed,
                           removed_files=removed_files, warnings=sorted(set(warnings)))
