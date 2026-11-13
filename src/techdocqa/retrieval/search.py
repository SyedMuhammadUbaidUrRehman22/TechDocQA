"""Query BM25, vector or hybrid search with common filters; the registry decides what may be returned."""

import hashlib
import json
import math

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.chunks import stored_chunks
from techdocqa.schemas import SearchRequest, SearchResponse, SearchResult

_lexical = None
# Hybrid (FR-14, P10-1 to P10-3): reciprocal rank fusion of both retrievers, judged on their component relevances.
FUSION_POLICY = "rrf-v1"
HYBRID_RELEVANCE_POLICY = "hybrid-component-relevance-v1"
COMPONENTS = ("bm25", "vector")


def digest(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fusion_values(settings) -> dict:
    retrieval = settings.retrieval
    return {"policy": FUSION_POLICY, "k": retrieval.rrf_k, "candidate_depth": retrieval.candidate_depth,
            "weights": {"bm25": retrieval.rrf_bm25_weight, "vector": retrieval.rrf_vector_weight}}


def scoring_values(mode: str, settings, profile: dict | None) -> dict:
    """What fixes a (query, chunk) relevance in this mode; thresholds are only valid on the scale these define.

    Hybrid's gate judges the fused chunks on both component scales, so its scale is both components plus the fusion
    that chooses which chunks are judged.
    """
    from techdocqa.indexing.embeddings import SCORE_POLICY
    from techdocqa.retrieval.lexical import RELEVANCE_POLICY, TOKENIZER_POLICY
    retrieval = settings.retrieval
    if mode == "hybrid":
        if profile is None:
            raise ValueError("hybrid scoring needs the embedding profile")
        return {"mode": mode, "relevance_policy": HYBRID_RELEVANCE_POLICY, "fusion": fusion_values(settings),
                "components": {"bm25": scoring_values("bm25", settings, None), "vector": scoring_values("vector", settings, profile)}}
    if profile:
        return {"mode": mode, "profile_id": profile["profile_id"], "score_policy": SCORE_POLICY}
    return {"mode": mode, "k1": retrieval.bm25_k1, "b": retrieval.bm25_b, "tokenizer": TOKENIZER_POLICY,
            "relevance_policy": RELEVANCE_POLICY}


def scoring_config_id(mode: str, settings, profile: dict | None) -> str:
    return "sc_" + digest(scoring_values(mode, settings, profile))


def retrieval_config_id(request: SearchRequest, settings, profile: dict | None) -> str:
    """Mode, depth, top-k, the score scale and the sufficiency thresholds that apply to it, with their calibration run."""
    from techdocqa.answering.sufficiency import active_thresholds
    values = {"top_k": request.top_k, "candidate_depth": settings.retrieval.candidate_depth,
              **scoring_values(request.mode, settings, profile)}
    thresholds, _ = active_thresholds(request.mode, settings, profile)
    values["sufficiency"] = thresholds.model_dump() if thresholds else None
    if request.mode == "hybrid":
        # Degraded hybrid is gated by the surviving mode's own thresholds, so they are part of this configuration.
        fallback = {name: active_thresholds(name, settings, profile if name == "vector" else None)[0] for name in COMPONENTS}
        values["fallback_sufficiency"] = {name: found.model_dump() if found else None for name, found in fallback.items()}
    if request.rerank:
        # Only a reranked request carries the reranker's identity, so the unreranked IDs never move with it.
        from techdocqa.answering.sufficiency import active_rerank_thresholds
        from techdocqa.retrieval import rerank
        reranked, _ = active_rerank_thresholds(request.mode, settings)
        values["rerank"] = {**rerank.scoring_values(settings, request.mode), "sufficiency": reranked.model_dump() if reranked else None}
    return "rc_" + digest(values)


def filtered_records(request: SearchRequest, eligible: list, inferred: dict[str, set[str]] | None = None) -> list:
    """A user category decides on its own; a document without one matches its current inferred categories, which
    include 'unclassified' (FR-09.4, P9-7). inferred is None when no category filter is requested."""
    def matches(value, wanted):
        return wanted is None or (value is not None and value.casefold() == wanted.casefold())
    def category_matches(record):
        wanted = request.filters.category
        if wanted is None or record.category is not None:
            return matches(record.category, wanted)
        return wanted.casefold() in (inferred or {}).get(record.version_id, set())
    filters = request.filters
    return [record for record in eligible
            if (filters.document_id is None or record.document_id == filters.document_id)
            and matches(record.technology, filters.technology) and category_matches(record)]


def inferred_categories(settings, registry) -> dict[str, set[str]]:
    """Read only for a category filter, so unfiltered search never touches enrichment rows."""
    from techdocqa.enrichment.classification import config_id
    from techdocqa.enrichment.pipeline import embedding_profile_or_none
    return registry.inferred_categories(config_id(settings.enrichment, embedding_profile_or_none(settings)))


def entity_filter_chunks(settings, registry, entity: str) -> set[str]:
    """A gazetteer alias resolves to its canonical name (Kafka to Apache Kafka), and only rows written under the active
    entity configuration count. Without a readable gazetteer there is no active configuration, so nothing matches."""
    from techdocqa.enrichment.entities import Gazetteer, config_id
    try:
        gazetteer = Gazetteer(settings.enrichment.gazetteer)
    except TechDocQAError:
        return set()
    return registry.entity_chunks(gazetteer.filter_key(entity),
                                  config_id(gazetteer, settings.enrichment.entity_verification_threshold))


def result(rank: int, mode: str, score: float, relevance: float, *, chunk_id, document_id, version_id, title, section_path,
           page, text) -> SearchResult:
    return SearchResult(rank=rank, chunk_id=chunk_id, document_id=document_id, version_id=version_id, title=title,
        section_path=section_path, page=page, text=text, scores={"bm25": None, "vector": None, mode: score}, ranks={mode: rank},
        relevance=relevance)


def lexical_index(settings, eligible: list):
    """Reused within a process until eligibility changes; a withdrawal or new version changes the key."""
    from techdocqa.retrieval.lexical import LexicalIndex
    global _lexical
    retrieval = settings.retrieval
    key = (retrieval.bm25_k1, retrieval.bm25_b, tuple((record.version_id, record.chunking.snapshot_hash) for record in eligible))
    if _lexical is None or _lexical[0] != key:
        chunks = [chunk for record in eligible for chunk in stored_chunks(record, settings)]
        _lexical = key, LexicalIndex(chunks, retrieval.bm25_k1, retrieval.bm25_b)
    return _lexical[1]


def bm25_ranked(request, settings, eligible, records, entity_chunks, depth: int) -> list[tuple[dict, float, float]]:
    """(chunk, raw score, relevance) for the first `depth` chunks, scored over every eligible chunk."""
    titles = {record.version_id for record in records}
    def allowed(chunk):
        return chunk["version_id"] in titles and (entity_chunks is None or chunk["chunk_id"] in entity_chunks)
    return lexical_index(settings, eligible).search(request.query, depth, allowed)


def chunk_fields(chunk: dict, titles: dict) -> dict:
    return {"chunk_id": chunk["chunk_id"], "document_id": chunk["document_id"], "version_id": chunk["version_id"],
            "title": titles[chunk["version_id"]], "section_path": " > ".join(chunk["section_path"]) or None,
            "page": chunk["page"], "text": chunk["text"]}


def bm25_results(request, settings, eligible, records, entity_chunks) -> list[SearchResult]:
    titles = {record.version_id: record.title for record in records}
    found = bm25_ranked(request, settings, eligible, records, entity_chunks, request.top_k)
    return [result(rank, "bm25", score, relevance, **chunk_fields(chunk, titles)) for rank, (chunk, score, relevance) in enumerate(found, 1)]


def vector_search(request, settings, records, entity_chunks, profile, depth: int):
    """(ranked (document, score) pairs, query vector, store, current versions); empty when no version is indexed."""
    from techdocqa.indexing.embeddings import embed_query
    from techdocqa.indexing.vector_store import VectorStore
    # A re-chunked or reactivated version answers lexically but waits here until it is indexed again.
    current = {record.version_id: record for record in records if record.status == "indexed"}
    if not current:
        return [], None, None, current
    store = VectorStore(settings.data_directory, profile["collection"])
    if store.empty():
        raise TechDocQAError("VECTOR_INDEX_MISSING", "The vector index is empty; run index --rebuild.", stage="search", retryable=True)
    where = {"version_id": {"$in": sorted(current)}}
    if entity_chunks is not None:
        where = {"$and": [where, {"chunk_id": {"$in": sorted(entity_chunks)}}]}
    vector = embed_query(request.query, settings, profile)
    found = store.search(vector, depth, where)
    live = [(document, score) for document, score in found
            if (record := current.get(document.metadata["version_id"]))
            and document.metadata["chunking_config_id"] == record.chunking.chunking_config_id]
    # Exact chunk_id tie-break keeps equal-distance repeated text reproducible.
    live.sort(key=lambda item: (-item[1], item[0].metadata["chunk_id"]))
    return live, vector, store, current


def document_fields(document, current: dict) -> dict:
    metadata = document.metadata
    return {"chunk_id": metadata["chunk_id"], "document_id": metadata["document_id"], "version_id": metadata["version_id"],
            "title": current[metadata["version_id"]].title, "section_path": metadata.get("section_path"),
            "page": metadata.get("page"), "text": document.page_content}


def vector_results(request, settings, records, entity_chunks, profile) -> list[SearchResult]:
    live, _, _, current = vector_search(request, settings, records, entity_chunks, profile,
                                        max(request.top_k, settings.retrieval.candidate_depth))
    # The FR-12 score is already the documented 0-1 relevance.
    return [result(rank, "vector", score, score, **document_fields(document, current))
            for rank, (document, score) in enumerate(live[:request.top_k], 1)]


def rrf(rankings: dict[str, list[str]], k: int, weights: dict[str, float]) -> list[tuple[str, float]]:
    """rrf-v1: score(c) = sum over the retrievers that ranked c of w_r / (k + rank_r(c)), ranks from 1; ties go to chunk_id.

    Retrievers are summed in a fixed order, so equal inputs give bit-identical scores.
    """
    scores: dict[str, float] = {}
    for name in sorted(rankings, key=lambda name: (COMPONENTS.index(name) if name in COMPONENTS else len(COMPONENTS), name)):
        for rank, chunk_id in enumerate(rankings[name], 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weights[name] / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def stored_relevances(store, query_vector: list[float], current: dict, chunk_ids: set[str]) -> dict[str, float]:
    """Vector relevance, (cosine + 1) / 2, from the stored vectors of chunks the vector search did not rank."""
    if not chunk_ids or store is None:
        return {}
    import numpy as np
    query = np.asarray(query_vector, dtype=np.float64)
    query_norm = float(np.linalg.norm(query))
    found = {}
    where = {"$and": [{"version_id": {"$in": sorted(current)}}, {"chunk_id": {"$in": sorted(chunk_ids)}}]}
    for metadata, stored in store.stored(where):
        record = current.get(metadata["version_id"])
        if record is None or metadata["chunking_config_id"] != record.chunking.chunking_config_id:
            continue
        vector = np.asarray(stored, dtype=np.float64)
        norm = query_norm * float(np.linalg.norm(vector))
        if norm == 0 or not math.isfinite(norm):
            continue
        found[metadata["chunk_id"]] = max(0.0, min(1.0, (1 + float(query @ vector) / norm) / 2))
    return found


def runtime_failure(error: TechDocQAError) -> bool:
    """A retriever failing at run time degrades hybrid; a request or configuration error is the caller's to fix."""
    return error.response.error.stage not in ("arguments", "configuration")


def hybrid_results(request, settings, eligible, records, entity_chunks, profile) -> tuple[list[SearchResult], str | None, str | None]:
    """(results, failed retriever, its error code). Both retrievers search to the candidate depth with the same filters."""
    retrieval = settings.retrieval
    depth = max(request.top_k, retrieval.candidate_depth)
    titles = {record.version_id: record.title for record in records}
    failures: dict[str, TechDocQAError] = {}
    lexical, live, query_vector, store, current = None, [], None, None, {}
    try:
        lexical = bm25_ranked(request, settings, eligible, records, entity_chunks, depth)
    except TechDocQAError as error:
        if not runtime_failure(error):
            raise
        failures["bm25"] = error
    try:
        live, query_vector, store, current = vector_search(request, settings, records, entity_chunks, profile, depth)
    except TechDocQAError as error:
        if not runtime_failure(error):
            raise
        failures["vector"] = error
    if len(failures) == len(COMPONENTS):
        codes = ", ".join(f"{name} {failures[name].response.error.code}" for name in COMPONENTS)
        # Both failing is a search failure, never empty evidence (SDD section 10).
        raise TechDocQAError("HYBRID_SEARCH_FAILED", f"Both hybrid retrievers failed: {codes}.", stage="search",
                             retryable=any(failures[name].response.error.retryable for name in COMPONENTS))
    fields, raw, relevance, rankings = {}, {name: {} for name in COMPONENTS}, {name: {} for name in COMPONENTS}, {}
    if lexical is not None:
        rankings["bm25"] = []
        for chunk, score, value in lexical:
            fields[chunk["chunk_id"]] = chunk_fields(chunk, titles)
            rankings["bm25"].append(chunk["chunk_id"])
            raw["bm25"][chunk["chunk_id"]], relevance["bm25"][chunk["chunk_id"]] = score, value
    if "vector" not in failures:
        rankings["vector"] = []
        for document, score in live[:depth]:
            chunk_id = document.metadata["chunk_id"]
            fields.setdefault(chunk_id, document_fields(document, current))
            rankings["vector"].append(chunk_id)
            raw["vector"][chunk_id] = relevance["vector"][chunk_id] = score
    weights = {"bm25": retrieval.rrf_bm25_weight, "vector": retrieval.rrf_vector_weight}
    fused = rrf(rankings, retrieval.rrf_k, weights)[:request.top_k]
    top = {chunk_id for chunk_id, _ in fused}
    # Every fused chunk carries both component relevances, not only where it ranked (P10-3).
    if lexical is not None and top - set(raw["bm25"]):
        for chunk_id, (score, value) in lexical_index(settings, eligible).scored(request.query, top - set(raw["bm25"])).items():
            raw["bm25"][chunk_id], relevance["bm25"][chunk_id] = score, value
    if "vector" not in failures and query_vector is not None:
        for chunk_id, value in stored_relevances(store, query_vector, current, top - set(raw["vector"])).items():
            raw["vector"][chunk_id] = relevance["vector"][chunk_id] = value
    failed = next(iter(failures), None)
    surviving = next((name for name in COMPONENTS if name != failed), None) if failed else None
    ranks = {name: {chunk_id: rank for rank, chunk_id in enumerate(ranked, 1)} for name, ranked in rankings.items()}
    results = [SearchResult(rank=rank, **fields[chunk_id],
                            scores={"bm25": raw["bm25"].get(chunk_id), "vector": raw["vector"].get(chunk_id), "hybrid": score},
                            ranks={**{name: ranks[name][chunk_id] for name in COMPONENTS if chunk_id in ranks.get(name, {})}, "hybrid": rank},
                            relevance=relevance[surviving].get(chunk_id) if surviving else None,
                            relevances={name: relevance[name].get(chunk_id) for name in COMPONENTS})
               for rank, (chunk_id, score) in enumerate(fused, 1)]
    return results, failed, failures[failed].response.error.code if failed else None


def search(request: SearchRequest, settings, registry, *, source_keys: frozenset[str] | None = None) -> SearchResponse:
    """source_keys limits the corpus itself, so BM25 statistics also come only from those sources (evaluation scope).

    With rerank, the mode's first rerank_max_candidates results are reranked and cut to top_k (FR-15).
    """
    from techdocqa.retrieval import rerank
    if request.rerank:
        rerank.require_configured(settings)
    profile = None
    if request.mode in ("vector", "hybrid"):
        from techdocqa.indexing.embeddings import embedding_profile
        profile = embedding_profile(settings.model)
    eligible = registry.eligible_versions()
    if source_keys is not None:
        eligible = [record for record in eligible if record.source_key in source_keys]
    inferred = inferred_categories(settings, registry) if request.filters.category is not None else None
    records = filtered_records(request, eligible, inferred)
    # A filter matches only verified entities (FR-07.3), so none means no results.
    entity_chunks = (entity_filter_chunks(settings, registry, request.filters.entity)
                     if request.filters.entity is not None else None)
    base = request.model_copy(update={"top_k": max(request.top_k, settings.retrieval.rerank_max_candidates)}) if request.rerank else request
    failed, reason, rerank_failure = None, None, None
    if not records or entity_chunks == set():
        results = []
    elif request.mode == "bm25":
        results = bm25_results(base, settings, eligible, records, entity_chunks)
    elif request.mode == "vector":
        results = vector_results(base, settings, records, entity_chunks, profile)
    else:
        results, failed, reason = hybrid_results(base, settings, eligible, records, entity_chunks, profile)
    if request.rerank and results:
        results, rerank_failure = rerank.rerank(request.query, results, request.top_k, settings)
    return SearchResponse(retrieval_config_id=retrieval_config_id(request, settings, profile), mode=request.mode,
                          degraded=failed is not None or rerank_failure is not None, degradation_reason=reason or rerank_failure,
                          failed_retriever=failed, reranked=request.rerank and bool(results) and rerank_failure is None,
                          rerank_failure=rerank_failure, results=results)
