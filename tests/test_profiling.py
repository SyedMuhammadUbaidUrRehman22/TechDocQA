"""The Phase 11 latency profiler (P11-1): stage wrapping, populations and report contents, offline."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from techdocqa.answering import generation
from techdocqa.evaluation.runner import run_evaluation
from techdocqa.ingestion.chunks import stored_chunks
# Shared fixtures: an indexed bench corpus with a counting embedder, and a scripted chat model.
from test_evaluation import bench  # noqa: F401
from test_generation import chat, qa_settings  # noqa: F401
from test_indexing import embedder, inline_workers, model_settings  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profile_latency", ROOT / "scripts" / "profile_latency.py")
profile_latency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile_latency)


def wrapped_values():
    found = []
    for owner_name, attribute, _, _ in profile_latency.STAGES + profile_latency.QA_STAGES:
        owner = profile_latency.resolve(owner_name)
        found.append(vars(owner)[attribute] if isinstance(owner, type) else getattr(owner, attribute))
    return found


def test_stage_timer_wraps_only_inside_its_block_and_restores_every_function():
    before = wrapped_values()
    with profile_latency.StageTimer(profile_latency.STAGES + profile_latency.QA_STAGES):
        inside = wrapped_values()
        assert all(new is not old for new, old in zip(inside, before))
    assert all(new is old for new, old in zip(wrapped_values(), before))


def test_retrieval_profile_times_every_search_and_moves_no_result(bench, model_settings, registry):
    fingerprint = run_evaluation(bench["dataset"], bench["manifest"], model_settings, registry)["results_fingerprint"]
    report = profile_latency.retrieval_profile(model_settings, registry, bench["dataset"], bench["manifest"],
                                               configurations=["bm25", "vector", "hybrid"], passes=2)
    rows = {row["configuration"]: row for row in report["configurations"]}
    assert report["scope"] == "evaluation" and report["scope_sources"] == 2 and report["passes"] == 2
    for row in rows.values():
        # 4 questions, 2 passes; the warm-up is not counted.
        assert row["latency_seconds"]["n"] == 8 and row["changed_rankings"] == 0 and row["degraded_searches"] == 0
        assert row["target_seconds"] == 1.0 and isinstance(row["met"], bool)
        # Top-level stages plus the unattributed remainder add up to the mean search time.
        parts = sum(row["stages"][name]["mean"] for name in profile_latency.top_level() if name in row["stages"])
        assert parts + row["stages"]["unattributed"]["mean"] == pytest.approx(row["latency_seconds"]["mean"], abs=2e-3)
    assert "bm25_search" in rows["bm25"]["stages"] and "query_embedding" not in rows["bm25"]["stages"]
    assert {"query_embedding", "embedder_build", "vector_store_open", "vector_search"} <= set(rows["vector"]["stages"])
    assert rows["vector"]["stages"]["embedder_build"]["inside"] == "query_embedding"
    assert {"bm25_search", "query_embedding", "vector_search"} <= set(rows["hybrid"]["stages"])
    assert [item["id"] for item in report["questions"]] == ["kafka-1", "kafka-2", "redis-1", "ood-1"]
    assert all(len(item["seconds"]["vector"]) == 2 for item in report["questions"])
    # Timing changes nothing: the same benchmark gives the same fingerprint afterwards.
    assert run_evaluation(bench["dataset"], bench["manifest"], model_settings, registry)["results_fingerprint"] == fingerprint
    report.update(code={"commit": "c" * 40, "dirty": False}, inventory=None)
    text = profile_latency.render_markdown(report)
    assert "| vector | 8 |" in text and "## Stages: hybrid" in text and "Runtime at start:" in text


def test_whole_scope_reports_timings_only_never_chunk_text_or_ids(bench, model_settings, registry):
    report = profile_latency.retrieval_profile(model_settings, registry, bench["dataset"], bench["manifest"],
                                               scope="whole", configurations=["bm25", "hybrid"], passes=1)
    assert report["scope"] == "whole" and report["scope_sources"] is None
    text = json.dumps(report)
    chunks = [chunk for record in registry.eligible_versions() for chunk in stored_chunks(record, model_settings)]
    assert chunks and not any(chunk["chunk_id"] in text for chunk in chunks)
    # Not even the questions' text: only their IDs and timings.
    assert "private notes" not in text and "replicate" not in text and "kafka-1" in text


ingestion_spec = importlib.util.spec_from_file_location("time_ingestion", ROOT / "scripts" / "time_ingestion.py")
time_ingestion = importlib.util.module_from_spec(ingestion_spec)
ingestion_spec.loader.exec_module(time_ingestion)


def test_ingestion_timing_starts_empty_counts_every_embedding_and_reports_hash_differences(model_settings, embedder,
                                                                                            inline_workers, tmp_path):
    sources = tmp_path / "frozen"
    sources.mkdir()
    (sources / "kafka.md").write_text("# Kafka guide\n\n" + "Kafka brokers replicate partitions across the cluster. " * 30, encoding="utf-8")
    (sources / "redis.html").write_text("<html><head><title>Redis guide</title></head><body><h1>Redis</h1><p>"
                                        + "Redis keeps keys in memory and evicts them by policy. " * 30 + "</p></body></html>", encoding="utf-8")
    manifest = {"documents": [
        {"snapshot_path": str(sources / "kafka.md"), "format": "md", "evaluation_included": True, "technology": "Kafka",
         "category": "Distributed streaming", "version_label": "4.3", "license": "Apache-2.0", "content_hash": "0" * 64},
        {"snapshot_path": str(sources / "redis.html"), "format": "html", "evaluation_included": False, "technology": "Redis",
         "category": None, "version_label": None, "license": None, "content_hash": "1" * 64}]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    scratch = tmp_path / "scratch"
    settings = model_settings.model_copy(update={"allowed_directories": [str(scratch / "corpus")], "data_directory": str(scratch / "data")})
    reference = time_ingestion.time_ingestion(settings, manifest_path, scratch, scope="reference", enrich=False)
    assert reference["documents"] == 1 and reference["formats"]["md"] == 1 and reference["failures"]["process"] == 0
    assert set(reference["stages_seconds"]) == {"ingest", "process", "chunk", "index"} and reference["with_enrich_seconds"] is None
    assert reference["chunks"] > 0 and reference["embedding"]["texts"] == reference["distinct_chunk_texts"]
    assert reference["cache_miss_proved"] and reference["met"]
    # A content hash that differs from the manifest is reported, never corrected.
    assert reference["content_hash_matches"] == 0 and len(reference["content_hash_differences"]) == 1
    scratch = tmp_path / "scratch-all"
    settings = model_settings.model_copy(update={"allowed_directories": [str(scratch / "corpus")], "data_directory": str(scratch / "data")})
    both = time_ingestion.time_ingestion(settings, manifest_path, scratch, scope="all", enrich=False)
    assert both["documents"] == 2 and both["formats"]["html"] == 1 and both["eligible_versions"] == 2
    assert both["cache_miss_proved"] and both["embedding"]["texts"] == both["distinct_chunk_texts"] > reference["distinct_chunk_texts"]
    # Counts, flags and timings only: no document text in the report.
    assert "replicate" not in json.dumps(both) and "evicts" not in json.dumps(both)
    both.update(code={"commit": "c" * 40, "dirty": False})
    assert "NFR-04 (at most 30 min" in time_ingestion.render_markdown(both)


def fake_response(status, total, *, llm_called, reason=None):
    retrieval = 0.3
    latency = {"retrieval": int(retrieval * 1000), "generation": int((total - retrieval) * 1000) if llm_called else 0,
               "total": int(total * 1000)}
    return SimpleNamespace(status=status, reason=reason, llm_called=llm_called, mode="hybrid", degraded=False,
                           latency_ms=SimpleNamespace(model_dump=lambda: latency))


def test_qa_p95_counts_only_questions_that_reached_generation_and_keeps_timeouts(bench, qa_settings, registry, monkeypatch):
    script = {"How do Kafka brokers replicate partitions?": fake_response("answered", 10.0, llm_called=True),
              "What does linger.ms do?": fake_response("generation_error", 61.0, llm_called=True, reason="LLM_TIMEOUT"),
              "How does Redis evict keys?": fake_response("no_evidence", 0.5, llm_called=False, reason="LOW_RELEVANCE")}
    monkeypatch.setattr(generation, "answer_question", lambda question, *args, **kwargs: script[question])
    monkeypatch.setattr(generation, "warm_up", lambda settings: {"loaded": True, "ms": 1, "code": None})
    report = profile_latency.qa_profile(qa_settings, registry, bench["dataset"], bench["manifest"])
    assert report["dataset"]["answerable"] == 3 and report["reached_generation"] == 2 and report["timed_out"] == 1
    # Nearest-rank p95 of [10, 61] is 61: the timeout counts as over the target instead of being dropped.
    assert report["seconds"]["total"]["p95"] == 61.0 and report["met"] is False
    assert report["gate_refused"]["questions"] == 1 and report["gate_refused"]["total_seconds"]["p95"] == 0.5
    assert report["statuses"] == {"answered": 1, "no_evidence": 1, "generation_error": 1}


def test_qa_profile_runs_the_real_answer_path_with_a_scripted_model(bench, qa_settings, registry, chat, monkeypatch):
    monkeypatch.setattr(generation, "warm_up", lambda settings: {"loaded": True, "ms": 1, "code": None})
    qa_settings.retrieval.mode = "bm25"
    report = profile_latency.qa_profile(qa_settings, registry, bench["dataset"], bench["manifest"])
    # No thresholds are calibrated here, so the gate is skipped and every question reaches the model.
    assert report["reached_generation"] == 3 and report["timed_out"] == 0 and report["mode"] == "bm25"
    assert {"bm25_search", "generation_call", "chat_model_build"} <= set(report["stages"])
    assert len(chat.prompts) == 3 and report["seconds"]["generation"]["n"] == 3
    report.update(code={"commit": "c" * 40, "dirty": False}, inventory=None)
    assert "NFR-03 (p95 at most 60.0 s)" in profile_latency.render_markdown(report)
