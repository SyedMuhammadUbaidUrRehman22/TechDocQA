"""Query either baseline retriever with common filters; the registry decides what may be returned."""

import hashlib
import json

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.chunks import stored_chunks
from techdocqa.schemas import SearchRequest, SearchResponse, SearchResult

_lexical = None


def digest(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scoring_values(mode: str, settings, profile: dict | None) -> dict:
    """What fixes a (query, chunk) relevance in this mode; thresholds are only valid on the scale these define."""
    from techdocqa.indexing.embeddings import SCORE_POLICY
    from techdocqa.retrieval.lexical import RELEVANCE_POLICY, TOKENIZER_POLICY
    retrieval = settings.retrieval
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


def bm25_results(request, settings, eligible, records, entity_chunks) -> list[SearchResult]:
    titles = {record.version_id: record.title for record in records}
    def allowed(chunk):
        return chunk["version_id"] in titles and (entity_chunks is None or chunk["chunk_id"] in entity_chunks)
    found = lexical_index(settings, eligible).search(request.query, request.top_k, allowed)
    return [result(rank, "bm25", score, relevance, chunk_id=chunk["chunk_id"], document_id=chunk["document_id"],
                   version_id=chunk["version_id"], title=titles[chunk["version_id"]],
                   section_path=" > ".join(chunk["section_path"]) or None, page=chunk["page"], text=chunk["text"])
            for rank, (chunk, score, relevance) in enumerate(found, 1)]


def vector_results(request, settings, records, entity_chunks, profile) -> list[SearchResult]:
    from techdocqa.indexing.embeddings import embed_query
    from techdocqa.indexing.vector_store import VectorStore
    # A re-chunked or reactivated version answers lexically but waits here until it is indexed again.
    current = {record.version_id: record for record in records if record.status == "indexed"}
    if not current:
        return []
    store = VectorStore(settings.data_directory, profile["collection"])
    if store.empty():
        raise TechDocQAError("VECTOR_INDEX_MISSING", "The vector index is empty; run index --rebuild.", stage="search", retryable=True)
    where = {"version_id": {"$in": sorted(current)}}
    if entity_chunks is not None:
        where = {"$and": [where, {"chunk_id": {"$in": sorted(entity_chunks)}}]}
    vector = embed_query(request.query, settings, profile)
    found = store.search(vector, max(request.top_k, settings.retrieval.candidate_depth), where)
    live = [(document, score) for document, score in found
            if (record := current.get(document.metadata["version_id"]))
            and document.metadata["chunking_config_id"] == record.chunking.chunking_config_id]
    # Exact chunk_id tie-break keeps equal-distance repeated text reproducible.
    live.sort(key=lambda item: (-item[1], item[0].metadata["chunk_id"]))
    # The FR-12 score is already the documented 0-1 relevance.
    return [result(rank, "vector", score, score, chunk_id=document.metadata["chunk_id"], document_id=document.metadata["document_id"],
                   version_id=document.metadata["version_id"], title=current[document.metadata["version_id"]].title,
                   section_path=document.metadata.get("section_path"), page=document.metadata.get("page"), text=document.page_content)
            for rank, (document, score) in enumerate(live[:request.top_k], 1)]


def search(request: SearchRequest, settings, registry, *, source_keys: frozenset[str] | None = None) -> SearchResponse:
    """source_keys limits the corpus itself, so BM25 statistics also come only from those sources (evaluation scope)."""
    if request.mode == "hybrid" or request.rerank:
        raise TechDocQAError("MODE_NOT_AVAILABLE", "Hybrid search and reranking are not implemented yet; use bm25 or vector.", stage="search")
    profile = None
    if request.mode == "vector":
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
    if not records or entity_chunks == set():
        results = []
    elif request.mode == "bm25":
        results = bm25_results(request, settings, eligible, records, entity_chunks)
    else:
        results = vector_results(request, settings, records, entity_chunks, profile)
    return SearchResponse(retrieval_config_id=retrieval_config_id(request, settings, profile), mode=request.mode, results=results)
