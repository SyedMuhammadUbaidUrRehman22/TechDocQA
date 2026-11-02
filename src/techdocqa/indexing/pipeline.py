"""Explicit embed-and-index runs over active chunks, reusing stored vectors (FR-11, FR-12, FR-20)."""

from techdocqa.chunking import effective_config
from techdocqa.errors import TechDocQAError
from techdocqa.indexing import embeddings
from techdocqa.indexing.vector_store import VectorStore
from techdocqa.ingestion.chunks import active_chunks
from techdocqa.schemas import BatchResult


class IndexingBatchResult(BatchResult):
    collection: str
    embedded_chunks: int = 0
    reused_chunks: int = 0
    failed_chunks: int = 0
    embedding_requests: int = 0
    indexed_entries: int = 0
    removed_entries: int = 0


def entry_metadata(chunk: dict, record, key: str) -> dict:
    """Scalar vector-store projection; a null is omitted and reads back as None."""
    values = {"chunk_id": chunk["chunk_id"], "chunk_key": key, "document_id": record.document_id,
              "version_id": record.version_id, "chunk_index": chunk["chunk_index"], "title": record.title,
              "section_path": " > ".join(chunk["section_path"]) or None, "technology": record.technology,
              "category": record.category, "page": chunk["page"], "text_hash": chunk["text_hash"],
              "chunking_config_id": chunk["chunking_config_id"]}
    return {name: value for name, value in values.items() if value is not None}


class Embedder:
    """Builds the provider only when a vector is actually missing, so a full rerun needs no provider."""

    def __init__(self, settings, profile, registry):
        self.settings, self.profile, self.registry = settings, profile, registry
        self.provider = None
        self.requests = self.embedded = self.failed = 0

    def embed(self, version_id: str, missing: dict[str, dict], by_key: dict[str, list[dict]]) -> None:
        if self.provider is None:
            self.provider = embeddings.build_embeddings(self.settings)
        model = self.settings.model
        keys = list(missing)
        for start in range(0, len(keys), model.embedding_batch_size):
            batch = keys[start:start + model.embedding_batch_size]
            try:
                self.requests += 1
                vectors = self.provider.embed_documents([model.embedding_prefix + missing[key]["text"] for key in batch])
                if len(vectors) != len(batch):
                    raise ValueError
            except Exception:
                # Provider failures vary by client; the batch is marked and later batches are not attempted.
                self.record(version_id, keys[start:], by_key, {}, "PROVIDER_ERROR")
                return
            valid = {}
            for key, vector in zip(batch, vectors, strict=True):
                reason = embeddings.invalid_reason(vector, self.profile)
                if reason:
                    self.record(version_id, [key], by_key, {}, reason)
                else:
                    valid[key] = embeddings.encode_vector(vector)
            self.record(version_id, list(valid), by_key, valid, None)

    def record(self, version_id, keys, by_key, vectors, reason):
        rows = [{"chunk": chunk, "key": key, "vector": vectors.get(key), "reason": reason}
                for key in keys for chunk in by_key[key]]
        self.registry.record_embeddings(version_id, self.profile["profile_id"], rows)
        if reason:
            self.failed += len(rows)
        else:
            self.embedded += len(rows)


def change_trigger(registry, record, profile, missing: dict[str, dict]) -> str:
    profile_id = profile["profile_id"]
    if registry.text_embedded_elsewhere(profile_id, {chunk["text_hash"] for chunk in missing.values()}):
        return "MODEL_CHANGED"
    return "CONTENT_CHANGED" if registry.document_embedded_before(record, profile_id) else "EMBEDDINGS_CREATED"


def index_version(record, settings, registry, store, profile, embedder, attempt_id, config_id) -> tuple[bool, int, int]:
    if record.chunking.chunking_config_id != config_id:
        raise TechDocQAError("STALE_CHUNKS", "Chunks predate the current configuration; run chunk first.",
                             stage="indexing", document_id=record.document_id)
    chunks = active_chunks(record.version_id, settings, registry)
    model_id = profile["embedding_model_id"]
    by_key = {}
    for chunk in chunks:
        by_key.setdefault(embeddings.chunk_key(chunk["text_hash"], chunk["chunking_config_id"], model_id), []).append(chunk)
    cached = registry.stored_keys(profile["profile_id"], list(by_key))
    missing = {key: group[0] for key, group in by_key.items() if key not in cached}
    reused = sum(len(group) for key, group in by_key.items() if key in cached)
    registry.record_embeddings(record.version_id, profile["profile_id"], [
        {"chunk": chunk, "key": key, "vector": None, "reason": None}
        for key, group in by_key.items() if key in cached for chunk in group])
    if missing:
        trigger = change_trigger(registry, record, profile, missing)
        before = embedder.requests
        embedder.embed(record.version_id, missing, by_key)
        left = set(missing) - registry.stored_keys(profile["profile_id"], list(missing))
        registry.log_embedding(record, attempt_id, trigger, f"{len(missing) - len(left)} embeddings created with {model_id} in "
                               f"{embedder.requests - before} provider requests; {reused} chunks reused; {len(left)} failed.")
        if left:
            raise TechDocQAError("EMBEDDING_FAILED", f"{len(left)} chunks have no valid embedding; rerun index to retry them.",
                                 stage="embedding", document_id=record.document_id, retryable=True)
    registry.set_index_status(record.version_id, "embedded", attempt_id)
    ids = [chunk["chunk_id"] for chunk in chunks]
    present = set()
    for start in range(0, len(ids), 256):
        present |= store.ids(ids=ids[start:start + 256])
    absent = [(key, chunk) for key, group in by_key.items() for chunk in group if chunk["chunk_id"] not in present]
    vectors = registry.load_vectors([key for key, _ in absent])
    store.upsert([(chunk["chunk_id"], chunk["text"], entry_metadata(chunk, record, key), embeddings.decode_vector(vectors[key]))
                  for key, chunk in absent])
    return not missing and not absent and record.status == "indexed", reused, len(absent)


def index_versions(version_ids: list[str], settings, registry, *, rebuild: bool = False) -> IndexingBatchResult:
    if rebuild and version_ids:
        raise TechDocQAError("INVALID_ARGUMENT", "A rebuild restores the whole index; do not name versions.", stage="arguments")
    profile = embeddings.embedding_profile(settings.model)
    config_id, _ = effective_config(settings.chunking, settings.model)
    with registry.registration_lock():
        registry.recover_interrupted_runs()
        version_ids = version_ids or [record.version_id for record in registry.eligible_versions()]
        if not version_ids:
            raise TechDocQAError("NO_ELIGIBLE_VERSIONS", "No active chunked versions are available.", stage="indexing")
        registry.save_embedding_profile(profile)
        store = VectorStore(settings.data_directory, profile["collection"])
        if rebuild:
            store.reset()
        run_id, attempts = registry.start_run(len(version_ids), stage="indexing")
        embedder = Embedder(settings, profile, registry)
        reused = indexed = 0
        for version_id, attempt_id in zip(version_ids, attempts, strict=True):
            try:
                record = registry.begin_indexing(version_id, attempt_id)
                skipped, reused_chunks, added = index_version(record, settings, registry, store, profile, embedder, attempt_id, config_id)
                registry.complete_indexing(version_id, attempt_id, skipped=skipped, entries=added)
                reused += reused_chunks
                indexed += added
            except TechDocQAError as error:
                registry.fail_attempt(attempt_id, error.response.error)
            except (OSError, ValueError, TypeError, KeyError):
                registry.fail_attempt(attempt_id, TechDocQAError("INDEXING_FAILED", "Indexing failed safely.", stage="indexing").response.error)
        registry.finish_run(run_id)
        # Registry eligibility already gates search; this removes what it now excludes.
        removed = store.delete(store.ids() - registry.indexed_chunk_ids(profile["profile_id"]))
        return IndexingBatchResult(**registry.get_run(run_id).model_dump(), collection=profile["collection"],
            embedded_chunks=embedder.embedded, reused_chunks=reused, failed_chunks=embedder.failed,
            embedding_requests=embedder.requests, indexed_entries=indexed, removed_entries=removed)
