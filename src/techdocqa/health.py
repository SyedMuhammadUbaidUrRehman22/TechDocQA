"""The `check` command (FR-24 behaviour 2, AC-24.3; P12-3).

Each dependency is probed once and reported `ok` or `down` with an error code and its time:

- registry: opens the existing registry and counts its documents; a missing registry is not created;
- vector_store: opens the active embedding profile's existing collection and counts its entries;
- bm25_index: builds the BM25 index over the eligible chunks and answers one fixed query;
- embedding_provider and llm_provider: list Ollama's installed models with a short timeout and compare the pinned
  digests; no model is loaded;
- reranker, only when reranking is enabled: its pinned files are hashed, and the model is not loaded.

The result is `down` when the registry or BM25 fails, since then no search can run; `degraded` when anything else
fails, since BM25 search still works; otherwise `ok`. Nothing in the data directory changes except one log line.
"""

import logging
from pathlib import Path
import time
from uuid import uuid4

from techdocqa.errors import TechDocQAError
from techdocqa.logs import log_event
from techdocqa.schemas import DependencyCheck, HealthReport, SearchRequest

# Listing models answers at once when Ollama runs; a model's own timeout covers loading it, which a check never does.
PROBE_TIMEOUT_SECONDS = 5
PROBE_QUERY = "configuration"
ESSENTIAL = {"registry", "bm25_index"}


def unavailable(code: str, message: str) -> TechDocQAError:
    return TechDocQAError(code, message, stage="check")


def probe(name: str, function) -> DependencyCheck:
    started = time.perf_counter()
    try:
        count, status, code = function(), "ok", None
    except TechDocQAError as error:
        count, status, code = None, "down", error.response.error.code
    except Exception:
        # A dependency's own exception text can hold paths or provider detail, so only a code is reported.
        count, status, code = None, "down", f"{name.upper()}_FAILED"
    return DependencyCheck(name=name, status=status, code=code, count=count,
                           latency_ms=round((time.perf_counter() - started) * 1000))


def vector_entries(settings) -> int:
    import chromadb
    from techdocqa.indexing.embeddings import embedding_profile
    profile = embedding_profile(settings.model)
    path = Path(settings.data_directory) / "index" / "chroma"
    if not path.is_dir():
        raise unavailable("VECTOR_INDEX_NOT_FOUND", "No vector index exists yet; run index first.")
    # The same client settings as the vector store, so a process that already opened it shares one client.
    client = chromadb.PersistentClient(path=str(path), settings=chromadb.config.Settings(
        anonymized_telemetry=False, is_persistent=True, persist_directory=str(path)))
    try:
        collection = client.get_collection(profile["collection"])
    except Exception:
        raise unavailable("VECTOR_INDEX_NOT_FOUND", "The active embedding profile has no vector collection; run index.") from None
    count = collection.count()
    if not count:
        raise unavailable("VECTOR_INDEX_EMPTY", "The vector collection holds no entries; run index.")
    return count


def bm25_chunks(settings, registry) -> int:
    if registry is None:
        raise unavailable("REGISTRY_UNAVAILABLE", "BM25 needs the registry.")
    from techdocqa.retrieval.search import lexical_index, search
    eligible = registry.eligible_versions()
    if not eligible:
        raise unavailable("NO_ACTIVE_CHUNKS", "No active chunked document is available to search.")
    search(SearchRequest(query=PROBE_QUERY, mode="bm25", top_k=1, rerank=False), settings, registry)
    return len(lexical_index(settings, eligible).chunks)


def installed_models(settings) -> dict[str, str] | None:
    """Ollama's installed models and their digests, or None when Ollama cannot be reached."""
    model = settings.model
    if model.provider != "ollama":
        return None
    try:
        import ollama
        timeout = min(PROBE_TIMEOUT_SECONDS, model.timeout_seconds or PROBE_TIMEOUT_SECONDS)
        return {item.model: item.digest for item in ollama.Client(host=model.base_url, timeout=timeout).list().models}
    except Exception:
        return None


def model_present(installed, name, digest, prefix: str) -> None:
    if installed is None:
        raise unavailable(f"{prefix}_PROVIDER_UNAVAILABLE", "The model provider is unreachable.")
    if not name:
        raise unavailable(f"{prefix}_MODEL_NOT_CONFIGURED", "No model is configured.")
    if name not in installed:
        raise unavailable(f"{prefix}_MODEL_NOT_FOUND", "The configured model is not installed.")
    if digest and installed[name] != digest:
        raise unavailable(f"{prefix}_MODEL_CHANGED", "The installed model does not match the pinned digest.")


def reranker_files(settings) -> int:
    from techdocqa.retrieval import cross_encoder
    from techdocqa.retrieval.rerank import require_configured
    require_configured(settings)
    pinned = settings.retrieval.reranker.files_sha256
    directory = cross_encoder.model_directory(settings)
    if not set(cross_encoder.REQUIRED_FILES) <= set(pinned) or any(
            not (directory / name).is_file() or cross_encoder.sha256(directory / name) != expected
            for name, expected in sorted(pinned.items())):
        raise unavailable("RERANKER_UNAVAILABLE", "The reranker's files are missing or do not match their pinned hashes.")
    return len(pinned)


def run_check(settings) -> HealthReport:
    from techdocqa.registry import Registry
    path = Path(settings.data_directory) / "registry.sqlite3"
    registry = None

    def open_registry() -> int:
        nonlocal registry
        if not path.is_file():
            raise unavailable("REGISTRY_NOT_FOUND", "No registry exists yet; ingest documents first.")
        registry = Registry(path)
        return registry.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    model = settings.model
    try:
        dependencies = [probe("registry", open_registry), probe("vector_store", lambda: vector_entries(settings)),
                        probe("bm25_index", lambda: bm25_chunks(settings, registry))]
        installed = installed_models(settings)
        dependencies += [
            probe("embedding_provider", lambda: model_present(installed, model.embedding_model, model.embedding_model_digest, "EMBEDDING")),
            probe("llm_provider", lambda: model_present(installed, model.chat_model, model.chat_model_digest, "LLM"))]
        if settings.retrieval.rerank:
            dependencies.append(probe("reranker", lambda: reranker_files(settings)))
    finally:
        if registry is not None:
            registry.close()
    down = {item.name for item in dependencies if item.status == "down"}
    status = "down" if down & ESSENTIAL else "degraded" if down else "ok"
    report = HealthReport(status=status, dependencies=dependencies, request_id=f"req_{uuid4().hex}")
    log_event("health", "CHECK_FINISHED", level=logging.INFO if status == "ok" else logging.WARNING,
              request_id=report.request_id, status=status,
              dependencies=[{"name": item.name, "status": item.status, "code": item.code} for item in dependencies])
    return report
