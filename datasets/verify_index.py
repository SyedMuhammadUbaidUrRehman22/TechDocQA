"""Check the real index against the registry; prints identifiers and counts, never document text.

Usage: verify_index.py [--snapshot FILE | --compare FILE] [--live]
--snapshot/--compare record and check top-5 results across a restart or rebuild (AC-12.6, AC-12.7).
--live also runs the provider checks: AC-11.5 stability, AC-12.1 sentence queries and query latency.
"""
import argparse
import json
from pathlib import Path
import re
import statistics
import sys
import time

import numpy as np

from techdocqa.indexing import embeddings
from techdocqa.indexing.pipeline import entry_metadata
from techdocqa.indexing.vector_store import VectorStore
from techdocqa.ingestion.chunks import active_chunks
from techdocqa.registry import Registry
from techdocqa.retrieval.search import search
from techdocqa.schemas import SearchFilters, SearchRequest
from techdocqa.settings import load_settings

QUERIES = [
    "How does Kafka replicate partitions?", "What does linger.ms do?", "How do Airflow tasks depend on each other?",
    "What is a Dag run?", "How do I submit a Spark application?", "How much memory does a Spark executor need?",
    "What does EXPLAIN ANALYZE show?", "What is serializable isolation?", "When should I use a GIN index?",
    "How does PostgreSQL implement MVCC?",
]
# Each occurs in the frozen public reference; the rank 1 chunk must contain it.
IDENTIFIERS = ["linger.ms", "enable.idempotence", "spark.memory.fraction", "spark.local.dir", "pg_subtrans",
               "wal_writer_delay", "idle_in_transaction_session_timeout", "execution_timeout"]
# A whole sentence: it follows a boundary, so it cannot be the tail of one cut by the chunk start.
SENTENCE = re.compile(r"(?<=[.!?]\s)[A-Z][^.!?\n]{40,300}[.!?]")
SAMPLE_EVERY = 3
TIMING_ROUNDS = 5


def check(condition, message):
    # Not assert: these are the verifier's results and must also run under python -O.
    if not condition:
        raise SystemExit(json.dumps({"result": "failed", "check": message}))


def run_query(settings, registry, text, mode, top_k=5, **filters):
    return search(SearchRequest(query=text, mode=mode, top_k=top_k, filters=SearchFilters(**filters)), settings, registry).results


def top_five(settings, registry):
    return {mode: {text: [[item.chunk_id, round(item.scores[mode], 6)] for item in run_query(settings, registry, text, mode)]
                   for text in QUERIES} for mode in ("bm25", "vector")}


def structural(settings, registry, profile):
    store = VectorStore(settings.data_directory, profile["collection"])
    stored = store.store.get(include=["metadatas", "embeddings"])
    entries = dict(zip(stored["ids"], stored["metadatas"], strict=True))
    dimensions = {len(vector) for vector in stored["embeddings"]}
    check(dimensions == {profile["dimension"]}, "stored vector dimension")
    expected = {}
    for record in registry.eligible_versions():
        check(record.status == "indexed", f"{record.version_id}: indexed")
        check(registry.get_document(record.document_id).document_id == record.document_id, "chunk to document")
        for chunk in active_chunks(record.version_id, settings, registry):
            key = embeddings.chunk_key(chunk["text_hash"], chunk["chunking_config_id"], profile["embedding_model_id"])
            expected[chunk["chunk_id"]] = entry_metadata(chunk, record, key)
    check(set(entries) == set(expected), "index entries equal eligible chunks")
    check(all(entries[chunk_id] == metadata for chunk_id, metadata in expected.items()), "metadata read-back equals registry")
    rows = registry.execute("SELECT status,COUNT(*) FROM chunk_embeddings WHERE profile_id=? GROUP BY status", (profile["profile_id"],)).fetchall()
    counts = {row[0]: row[1] for row in rows}
    check(not counts.get("embedding_failed"), "no failed chunk embeddings")
    keys = {metadata["chunk_key"] for metadata in expected.values()}
    check(registry.stored_keys(profile["profile_id"], list(keys)) == keys, "every chunk has a stored vector")
    check(registry.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "sqlite integrity")
    check(not registry.execute("PRAGMA foreign_key_check").fetchall(), "sqlite foreign keys")
    return {"index_entries": len(entries), "stored_vectors": len(keys), "repeated_text_occurrences": len(entries) - len(keys)}


def identifier_checks(settings, registry):
    results = {}
    for identifier in IDENTIFIERS:
        found = run_query(settings, registry, identifier, "bm25", top_k=1)
        results[identifier] = bool(found) and identifier in found[0].text
    return results


def sentence_checks(settings, registry, profile, embedder, reference_ids):
    """AC-12.1 on the real corpus, separating index recall from what exact search itself can achieve."""
    chunks = [chunk for record in registry.eligible_versions() for chunk in active_chunks(record.version_id, settings, registry)]
    keys = [embeddings.chunk_key(chunk["text_hash"], chunk["chunking_config_id"], profile["embedding_model_id"]) for chunk in chunks]
    stored = registry.load_vectors(keys)
    matrix = np.stack([np.frombuffer(stored[key], dtype=np.float32) for key in keys])
    public = np.array([chunk["document_id"] in reference_ids for chunk in chunks])
    # The overlap prefix also belongs to the preceding chunk, so it cannot identify this one.
    sampled = [(index, match.group().strip()) for index, chunk in enumerate(chunks)
               if public[index] and (match := SENTENCE.search(chunk["text"], chunk["overlap_characters"]))][::SAMPLE_EVERY]
    index_hits = exact_hits = public_hits = agreement = 0
    for index, sentence in sampled:
        vector = np.asarray(embedder.embed_query(settings.model.embedding_query_prefix + sentence), dtype=np.float32)
        order = np.argsort(-(matrix @ vector))
        exact = [chunks[position]["chunk_id"] for position in order[:3]]
        found = [item.chunk_id for item in run_query(settings, registry, sentence, "vector", top_k=3)]
        index_hits += chunks[index]["chunk_id"] in found
        exact_hits += chunks[index]["chunk_id"] in exact
        public_hits += index in order[public[order]][:3]
        agreement += set(found) == set(exact)
    return {"sentence_queries": len(sampled), "index_top3_hits": index_hits, "exact_top3_hits": exact_hits,
            "exact_top3_hits_public_only": public_hits, "index_equals_exact_top3": agreement}


def live_checks(settings, registry, profile, reference_ids):
    embedder = embeddings.build_embeddings(settings)
    text = settings.model.embedding_prefix + "Kafka stores events durably in partitioned logs."
    one, two = (np.asarray(vector) for vector in embedder.embed_documents([text, text]))
    three = np.asarray(embedder.embed_documents([text])[0])
    cosine = lambda left, right: float(left @ right / (np.linalg.norm(left) * np.linalg.norm(right)))
    timings = {}
    for mode in ("bm25", "vector"):
        run_query(settings, registry, QUERIES[0], mode)
        samples = []
        for _ in range(TIMING_ROUNDS):
            for query in QUERIES:
                started = time.perf_counter()
                run_query(settings, registry, query, mode)
                samples.append(time.perf_counter() - started)
        samples.sort()
        timings[mode] = {"queries": len(samples), "median_seconds": round(statistics.median(samples), 3),
                         "p95_seconds": round(samples[int(0.95 * len(samples)) - 1], 3), "max_seconds": round(samples[-1], 3)}
    return {"same_text_min_cosine": min(cosine(one, two), cosine(one, three)),
            **sentence_checks(settings, registry, profile, embedder, reference_ids), "warm_query_timing": timings}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root / "config/default.toml")
    manifest = json.loads((root / "datasets/corpus_manifest.json").read_text(encoding="utf-8"))
    source_keys = {item["source_key"] for item in manifest["documents"] if item["evaluation_included"]}
    profile = embeddings.embedding_profile(settings.model)
    output = {"collection": profile["collection"]}
    with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
        output.update(structural(settings, registry, profile))
        output["identifier_rank1"] = identifier_checks(settings, registry)
        if args.snapshot or args.compare:
            current = top_five(settings, registry)
            if args.snapshot:
                args.snapshot.write_text(json.dumps(current), encoding="utf-8")
                output["snapshot_queries"] = sum(len(queries) for queries in current.values())
            if args.compare:
                saved = json.loads(args.compare.read_text(encoding="utf-8"))
                output["top5_identical"] = {mode: current[mode] == saved[mode] for mode in current}
                check(all(output["top5_identical"].values()), "top-5 results changed")
        if args.live:
            reference = {record.document_id for record in registry.eligible_versions() if record.source_key in source_keys}
            output["live"] = live_checks(settings, registry, profile, reference)
    print(json.dumps({**output, "result": "passed"}))


if __name__ == "__main__":
    sys.exit(main())
