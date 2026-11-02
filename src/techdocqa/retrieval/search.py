"""Query either baseline retriever with common filters; the registry decides what may be returned."""

import hashlib
import json

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.chunks import stored_chunks
from techdocqa.schemas import SearchRequest, SearchResponse, SearchResult

_lexical = None


def retrieval_config_id(request: SearchRequest, settings, profile: dict | None) -> str:
    from techdocqa.indexing.embeddings import SCORE_POLICY
    from techdocqa.retrieval.lexical import TOKENIZER_POLICY
    retrieval = settings.retrieval
    values = {"mode": request.mode, "top_k": request.top_k, "candidate_depth": retrieval.candidate_depth}
    if profile:
        values.update(profile_id=profile["profile_id"], score_policy=SCORE_POLICY)
    else:
        values.update(k1=retrieval.bm25_k1, b=retrieval.bm25_b, tokenizer=TOKENIZER_POLICY)
    return "rc_" + hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def filtered_records(request: SearchRequest, eligible: list) -> list:
    def matches(value, wanted):
        return wanted is None or (value is not None and value.casefold() == wanted.casefold())
    filters = request.filters
    return [record for record in eligible
            if (filters.document_id is None or record.document_id == filters.document_id)
            and matches(record.technology, filters.technology) and matches(record.category, filters.category)]


def result(rank: int, mode: str, score: float, *, chunk_id, document_id, version_id, title, section_path, page, text) -> SearchResult:
    return SearchResult(rank=rank, chunk_id=chunk_id, document_id=document_id, version_id=version_id, title=title,
        section_path=section_path, page=page, text=text, scores={"bm25": None, "vector": None, mode: score}, ranks={mode: rank})


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
    return [result(rank, "bm25", score, chunk_id=chunk["chunk_id"], document_id=chunk["document_id"], version_id=chunk["version_id"],
                   title=titles[chunk["version_id"]], section_path=" > ".join(chunk["section_path"]) or None,
                   page=chunk["page"], text=chunk["text"])
            for rank, (chunk, score) in enumerate(found, 1)]


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
    return [result(rank, "vector", score, chunk_id=document.metadata["chunk_id"], document_id=document.metadata["document_id"],
                   version_id=document.metadata["version_id"], title=current[document.metadata["version_id"]].title,
                   section_path=document.metadata.get("section_path"), page=document.metadata.get("page"), text=document.page_content)
            for rank, (document, score) in enumerate(live[:request.top_k], 1)]


def search(request: SearchRequest, settings, registry) -> SearchResponse:
    if request.mode == "hybrid" or request.rerank:
        raise TechDocQAError("MODE_NOT_AVAILABLE", "Hybrid search and reranking are not implemented yet; use bm25 or vector.", stage="search")
    profile = None
    if request.mode == "vector":
        from techdocqa.indexing.embeddings import embedding_profile
        profile = embedding_profile(settings.model)
    eligible = registry.eligible_versions()
    records = filtered_records(request, eligible)
    # P0 has no entity extractor: a filter matches only verified associations, so none means no results.
    entity_chunks = registry.entity_chunks(request.filters.entity) if request.filters.entity is not None else None
    if not records or entity_chunks == set():
        results = []
    elif request.mode == "bm25":
        results = bm25_results(request, settings, eligible, records, entity_chunks)
    else:
        results = vector_results(request, settings, records, entity_chunks, profile)
    return SearchResponse(retrieval_config_id=retrieval_config_id(request, settings, profile), mode=request.mode, results=results)
