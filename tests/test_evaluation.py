"""FR-19 smoke slice, AC-21.3 deletion flags and the eval CLI, offline with the counting fake embedder."""

from itertools import product
import json
from pathlib import Path

import pytest

from techdocqa.cli import main
from techdocqa.errors import TechDocQAError
from techdocqa.evaluation.dataset import load_dataset
from techdocqa.evaluation.metrics import (METRICS, P0_METRICS, macro_average, ndcg_at_k, p95, paired_bootstrap, precision_at_k,
                                          question_metrics, recall_at_k, reciprocal_rank)
from techdocqa.evaluation.runner import P0_SUMMARY_KEYS, fingerprinted, render_markdown, results_fingerprint, run_evaluation
from techdocqa.indexing.lifecycle import delete_document, withdraw_document
from techdocqa.indexing.pipeline import index_versions
from techdocqa.ingestion.chunks import active_chunks
# Shared Phase 5 fixtures: inline processing workers, the counting embedder and a verified model profile.
from test_indexing import embedder, ingest, inline_workers, model_settings  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TECHNOLOGIES = {"Apache Kafka", "Apache Airflow", "Apache Spark", "PostgreSQL"}
DOCUMENTS = {
    "kafka.md": "# Kafka guide\n\n## Replication\n\n" + "Kafka brokers replicate partitions across the cluster. " * 10
                + "\n\n## Producers\n\n" + "The linger.ms setting delays sends so records batch together. " * 10,
    "redis.md": "# Redis guide\n\n" + "Redis keeps keys in memory and evicts them by policy. " * 12,
    # Stands in for the private supplement: indexed and searchable, but outside the evaluation manifest.
    "private.md": "# Private notes\n\n" + "Kafka brokers replicate partitions, say these private notes. " * 12,
}


def question(id, text, *items, unanswerable=False, review="draft"):
    record = {"id": id, "question": text, "type": "factual", "relevant": list(items), "review": review}
    return {**record, "unanswerable": True} if unanswerable else record


def write_lines(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


@pytest.fixture
def bench(corpus, model_settings, registry, embedder, tmp_path):
    versions = {}
    for name, body in DOCUMENTS.items():
        (corpus / name).write_text(body, encoding="utf-8")
        versions[name] = ingest(corpus / name, model_settings, registry)
    assert index_versions([], model_settings, registry).run.failed == 0
    keys = {name: registry.get_document(version.document_id).source_key for name, version in versions.items()}
    manifest = {"dataset_id": "test-reference", "status": "frozen", "reference_fingerprint_sha256": "0" * 64, "documents": [
        {"source_key": keys[name], "document_id": version.document_id, "evaluation_included": name != "private.md",
         "content_hash": registry.get_version(version.version_id).content_hash} for name, version in versions.items()]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset = write_lines(tmp_path / "bench.jsonl", [
        {**question("kafka-1", "How do Kafka brokers replicate partitions?",
                    {"source_key": keys["kafka.md"], "anchor": "Kafka brokers replicate  partitions across the CLUSTER"}), "technology": "Kafka"},
        {**question("kafka-2", "What does linger.ms do?", {"source_key": keys["kafka.md"], "section": "Kafka guide > Producers"}), "technology": "Kafka"},
        {**question("redis-1", "How does Redis evict keys?", {"source_key": keys["redis.md"], "anchor": "evicts them by policy"}), "technology": "Redis"},
        question("ood-1", "How do Terraform workspaces work?", unanswerable=True),
    ])
    return {"versions": versions, "keys": keys, "manifest": manifest_path, "dataset": dataset}


def run(bench, settings, registry, **kwargs):
    return run_evaluation(bench["dataset"], bench["manifest"], settings, registry, **kwargs)


# Metrics (AC-19.3)

def test_metrics_match_hand_computed_examples():
    # Ranks: miss, a (grade 2), miss, b (grade 1), a again. Gains: a 2^2 - 1 = 3, b 2^1 - 1 = 1.
    matches = [set(), {"a"}, set(), {"b"}, {"a"}]
    values = question_metrics(matches, {"a": 2, "b": 1})
    assert {name: values[name] for name in P0_METRICS} == {"recall@1": 0.0, "recall@3": 0.5, "recall@5": 1.0, "mrr": 0.5}
    # Credited positions are 2 and 4; the repeat of a at rank 5 earns nothing. 0/1, 1/3, 2/5.
    assert values["precision@1"] == 0.0 and values["precision@3"] == pytest.approx(1 / 3) and values["precision@5"] == 0.4
    # Ideal: a then b, 3/log2(2) + 1/log2(3) = 3 + 0.630930 = 3.630930.
    # @3: 3/log2(3) = 1.892789, / 3.630930 = 0.521296. @5: (1.892789 + 1/log2(5) = 0.430677) / 3.630930 = 0.639909.
    assert values["ndcg@1"] == 0.0
    assert values["ndcg@3"] == pytest.approx(0.521296, abs=1e-6) and values["ndcg@5"] == pytest.approx(0.639909, abs=1e-6)
    # The requirement's example: first relevant result at rank 2 gives MRR 0.5.
    assert reciprocal_rank([set(), {"x"}], {"x"}) == 0.5
    assert reciprocal_rank([{"x"}], {"x"}) == 1.0
    assert reciprocal_rank([set(), set(), {"x"}], {"x"}) == pytest.approx(1 / 3)
    assert question_metrics([set()] * 5, {"x": 2}) == {name: 0.0 for name in METRICS}


def test_a_chunk_holding_two_items_is_credited_once_and_stays_within_one():
    # One chunk at rank 1 holds a and b, both grade 2 (gain 3): one credited position, one gain.
    values = question_metrics([{"a", "b"}, set(), set()], {"a": 2, "b": 2})
    assert values["recall@1"] == 1.0 and values["precision@1"] == 1.0 and values["ndcg@1"] == 1.0
    # @3: 1 credited position / 3. DCG 3/log2(2) = 3; ideal 3 + 3/log2(3) = 3 + 1.892789 = 4.892789; 3 / 4.892789 = 0.613147.
    assert values["precision@3"] == pytest.approx(1 / 3) and values["ndcg@3"] == pytest.approx(0.613147, abs=1e-6)


def test_missing_results_count_as_misses_and_the_ideal_uses_only_labeled_items():
    # One result, one grade-1 item: precision keeps K as its denominator; the ideal has one item, so nDCG is 1.
    values = question_metrics([{"a"}], {"a": 1})
    assert values["precision@1"] == 1.0 and values["precision@3"] == pytest.approx(1 / 3) and values["precision@5"] == 0.2
    assert values["ndcg@5"] == 1.0 and values["recall@5"] == 1.0
    assert precision_at_k([], {"a"}, 5) == 0.0 and ndcg_at_k([], {"a": 2}, 5) == 0.0


def test_ndcg_rewards_grade_order_and_ignores_grade_zero_items():
    # b (grade 1, gain 1) before a (grade 2, gain 3). @1: 1 / 3 = 0.333333.
    # @3: (1/log2(2) + 3/log2(3) = 1 + 1.892789 = 2.892789) / (3 + 1/log2(3) = 3.630930) = 0.796708.
    values = question_metrics([{"b"}, {"a"}], {"a": 2, "b": 1})
    assert values["ndcg@1"] == pytest.approx(1 / 3) and values["ndcg@3"] == pytest.approx(0.796708, abs=1e-6)
    assert question_metrics([{"a"}, {"b"}], {"a": 2, "b": 1})["ndcg@3"] == 1.0
    # A grade-0 item is labeled non-relevant: it is never credited and never enters the ideal.
    # @3: 3/log2(3) = 1.892789, ideal 3/log2(2) = 3, 0.630930.
    values = question_metrics([{"z"}, {"a"}], {"a": 2, "z": 0})
    assert values["precision@1"] == 0.0 and values["mrr"] == 0.5 and values["ndcg@3"] == pytest.approx(0.630930, abs=1e-6)
    with pytest.raises(ValueError):
        ndcg_at_k([{"z"}], {"z": 0}, 1)
    with pytest.raises(ValueError):
        precision_at_k([{"a"}], set(), 1)


def test_every_metric_stays_between_zero_and_one():
    # Every ranking of up to four results drawn from two labeled items and a miss, under every grading.
    subsets = [set(), {"a"}, {"b"}, {"x"}, {"a", "b"}, {"a", "x"}, {"b", "x"}, {"a", "b", "x"}]
    gradings = [{"a": first, "b": second} for first, second in product((0, 1, 2), repeat=2) if first or second]
    checked = 0
    for grades in gradings:
        for length in range(5):
            for ranking in product(subsets, repeat=length):
                values = question_metrics(list(ranking), grades)
                assert all(0 <= value <= 1 + 1e-12 for value in values.values()), (ranking, grades, values)
                checked += 1
    assert checked == 8 * sum(8 ** length for length in range(5))


def test_an_item_found_twice_counts_once_and_grade_zero_items_never_count():
    assert recall_at_k([{"a"}, {"a"}, {"a"}], {"a", "b"}, 3) == 0.5
    assert recall_at_k([], {"a"}, 5) == 0.0
    with pytest.raises(ValueError):
        recall_at_k([{"a"}], set(), 1)
    with pytest.raises(ValueError):
        reciprocal_rank([{"a"}], set())


def test_macro_average_is_unweighted_and_empty_is_none():
    rows = [{"recall@1": 1.0, "recall@3": 1.0, "recall@5": 1.0, "mrr": 1.0},
            {"recall@1": 0.0, "recall@3": 0.5, "recall@5": 1.0, "mrr": 0.25}]
    assert macro_average(rows, P0_METRICS) == {"recall@1": 0.5, "recall@3": 0.75, "recall@5": 1.0, "mrr": 0.625}
    assert macro_average([]) == {name: None for name in METRICS}


# Paired differences (P10-6, P10-7)

def test_bootstrap_interval_is_exact_for_constant_differences_and_zero_is_not_a_benefit():
    assert paired_bootstrap([0.2] * 7) == {"n": 7, "mean_difference": pytest.approx(0.2), "interval": [pytest.approx(0.2)] * 2,
                                           "better": 7, "worse": 0, "tied": 0}
    tied = paired_bootstrap([0.0] * 7)
    # The rule needs the lower bound strictly above 0.
    assert tied["interval"] == [0.0, 0.0] and not tied["interval"][0] > 0 and tied["tied"] == 7
    with pytest.raises(ValueError):
        paired_bootstrap([])


def test_bootstrap_interval_trims_250_means_from_each_end():
    # Two questions: a resampled mean is 0, 0.5 or 1 with probability 1/4, 1/2, 1/4, so about 2,500 means are 0 and
    # 2,500 are 1. Dropping 250 from each end of 10,000 leaves 0 and 1 as the bounds, whatever the seed.
    result = paired_bootstrap([1.0, 0.0])
    assert result["interval"] == [0.0, 1.0] and result["mean_difference"] == 0.5
    assert (result["better"], result["tied"], result["worse"]) == (1, 1, 0)


def test_bootstrap_is_repeatable_for_a_fixed_seed():
    differences = [0.5, -0.25, 0.0, 1.0, 0.125, -0.5, 0.75]
    assert paired_bootstrap(differences) == paired_bootstrap(differences)
    assert paired_bootstrap(differences)["interval"] != paired_bootstrap(differences, seed=1)["interval"]


def test_p95_is_the_nearest_rank_value():
    assert p95([]) is None and p95([4.0]) == 4.0
    # ceil(0.95 * 20) = 19th, ceil(0.95 * 30) = ceil(28.5) = 29th, ceil(0.95 * 50) = ceil(47.5) = 48th.
    assert p95(list(range(1, 21))) == 19 and p95(list(range(30, 0, -1))) == 29 and p95(list(range(1, 51))) == 48


# Loader (AC-19.5)

ANCHOR = {"source_key": "doc", "anchor": "some passage"}


@pytest.mark.parametrize("record, reason", [
    (question("q", "Text?"), "needs a relevant item"),
    (question("q", "Text?", {**ANCHOR, "grade": 0}), "needs a relevant item"),
    (question("q", "Text?", ANCHOR, unanswerable=True), "unanswerable one has none"),
    (question("q", "Text?", {"source_key": "doc"}), "anchor or a section"),
    ({k: v for k, v in question("q", "Text?", ANCHOR).items() if k != "review"}, "Field required"),
    (question("Q 1", "Text?", ANCHOR), "pattern"),
])
def test_loader_rejects_a_question_without_expected_items_unless_unanswerable(tmp_path, record, reason):
    path = write_lines(tmp_path / "bench.jsonl", [question("ok", "Fine?", ANCHOR), record])
    with pytest.raises(TechDocQAError) as error:
        load_dataset(path)
    assert error.value.response.error.code == "INVALID_BENCHMARK"
    assert "line 2" in error.value.response.error.message and reason in error.value.response.error.message


def test_loader_accepts_unanswerable_and_rejects_duplicates_and_bad_json(tmp_path):
    path = write_lines(tmp_path / "bench.jsonl", [question("ok", "Fine?", ANCHOR, {**ANCHOR, "grade": 0}),
                                                  question("none", "Nothing?", unanswerable=True)])
    dataset = load_dataset(path)
    assert [item.id for item in dataset.questions] == ["ok", "none"] and dataset.dataset_id == "bench"
    for lines in ([question("a", "A?", ANCHOR)] * 2, None):
        target = tmp_path / "bad.jsonl"
        if lines:
            write_lines(target, lines)
        else:
            target.write_text('{"id": "a",\n', encoding="utf-8")
        with pytest.raises(TechDocQAError) as error:
            load_dataset(target)
        assert error.value.response.error.code == "INVALID_BENCHMARK"
    with pytest.raises(TechDocQAError) as error:
        load_dataset(tmp_path / "missing.jsonl")
    assert error.value.response.error.code == "BENCHMARK_NOT_READABLE"


def test_dataset_hash_covers_the_exact_bytes(tmp_path):
    path = write_lines(tmp_path / "bench.jsonl", [question("ok", "Fine?", ANCHOR)])
    first = load_dataset(path).sha256
    path.write_text(path.read_text(encoding="utf-8").replace('"draft"', '"reviewed"'), encoding="utf-8")
    assert load_dataset(path).sha256 != first


def test_repository_smoke_benchmark_has_the_required_composition():
    dataset = load_dataset(ROOT / "datasets/benchmark_smoke.jsonl")
    manifest = json.loads((ROOT / "datasets/corpus_manifest.json").read_text(encoding="utf-8"))
    public = {item["source_key"] for item in manifest["documents"] if item["evaluation_included"]}
    answerable = [item for item in dataset.questions if not item.unanswerable]
    assert len(dataset.questions) == 30 and len(answerable) == 20
    assert all(not item.relevant for item in dataset.questions if item.unanswerable)
    assert {item.technology for item in answerable} == TECHNOLOGIES
    assert all(sum(item.technology == technology for item in answerable) == 5 for technology in TECHNOLOGIES)
    assert {item.type for item in dataset.questions} == {"factual", "how_to", "identifier"}
    # Labels name only the frozen public reference; the private supplement never carries one.
    assert {label.source_key for item in answerable for label in item.relevant} <= public


def test_repository_full_benchmark_keeps_smoke_and_adds_twenty():
    """P10-8: the smoke lines byte for byte, then 4 answerable per technology and 4 in-domain negatives."""
    smoke = (ROOT / "datasets/benchmark_smoke.jsonl").read_bytes()
    assert (ROOT / "datasets/benchmark_full.jsonl").read_bytes().startswith(smoke)
    dataset = load_dataset(ROOT / "datasets/benchmark_full.jsonl")
    manifest = json.loads((ROOT / "datasets/corpus_manifest.json").read_text(encoding="utf-8"))
    public = {item["source_key"] for item in manifest["documents"] if item["evaluation_included"]}
    new = [item for item in dataset.questions if item.id.startswith("full-")]
    assert len(dataset.questions) == 50 and len(new) == 20
    assert sum(item.unanswerable for item in dataset.questions) == 14
    for technology in TECHNOLOGIES:
        rows = [item for item in new if item.technology == technology]
        answerable = [item for item in rows if not item.unanswerable]
        assert len(rows) == 5 and len(answerable) == 4
        assert {"identifier", "how_to"} <= {item.type for item in answerable}
    assert {label.source_key for item in new for label in item.relevant} <= public


# Runs (AC-19.1, AC-19.4)

def test_run_reports_both_modes_with_dataset_corpus_and_configuration_identity(bench, model_settings, registry):
    report = run(bench, model_settings, registry)
    assert [row["mode"] for row in report["configurations"]] == ["bm25", "vector"]
    for row in report["configurations"]:
        assert row["status"] == "completed" and row["retrieval_config_id"].startswith("rc_")
        assert row["evaluated_questions"] == 3 and row["excluded_questions"] == 0
        assert set(row["metrics"]) == set(METRICS)
        assert all(0 <= value <= 1 for value in row["metrics"].values())
        assert set(row["by_technology"]) == {"Kafka", "Redis"}
        assert set(row["by_technology"]["Kafka"]) == {"questions", *METRICS}
        assert 0 < row["latency_seconds"]["median"] <= row["latency_seconds"]["p95"] <= row["latency_seconds"]["max"]
    assert report["dataset"]["sha256"] == load_dataset(bench["dataset"]).sha256 and report["dataset"]["draft"] == 4
    assert report["corpus"]["searchable_documents"] == 2 and report["corpus"]["excluded_eligible_documents"] == 1
    assert len(report["corpus"]["corpus_fingerprint"]) == 64 and report["within_time_limit"]
    assert report["environment"]["embedding"]["digest"] == "a" * 64 and report["environment"]["libraries"]["pydantic"]
    assert report["flags"] == [] and any("drafts without second-person review" in note for note in report["notes"])
    by_id = {item["id"]: item for item in report["questions"]}
    # Whitespace and case in an anchor do not matter; a section label matches every chunk under it.
    assert by_id["kafka-1"]["items"][0]["resolved_chunks"] >= 1 and by_id["kafka-2"]["items"][0]["resolved_chunks"] >= 1
    assert by_id["kafka-1"]["results"]["bm25"]["first_relevant_rank"] == 1


# Run records (NFR-05, P11-5)

def test_runtime_is_recorded_offline_and_never_enters_the_fingerprint(bench, model_settings, registry, monkeypatch):
    from techdocqa.evaluation import runtime
    first = run(bench, model_settings, registry)
    recorded = first["environment"]
    # Offline the server is never contacted; the socket guard would fail the test if it were.
    assert recorded["ollama"] == {"version": None, "loaded": None, "note": "offline: not contacted"}
    assert {"processor", "logical_cpus", "ram_total_bytes", "ram_available_bytes", "ac_power"} <= set(recorded["machine"])
    assert recorded["libraries"]["onnxruntime"] and recorded["libraries"]["tokenizers"] and recorded["python"]
    monkeypatch.setattr(runtime, "machine", lambda: {"logical_cpus": 1})
    monkeypatch.setattr(runtime, "ollama_state", lambda base_url: {"version": "9.9.9", "loaded": []})
    second = run(bench, model_settings, registry)
    assert second["environment"]["ollama"]["version"] == "9.9.9"
    assert second["results_fingerprint"] == first["results_fingerprint"]
    assert "- Runtime: Python " in render_markdown(second) and "Ollama 9.9.9" in render_markdown(second)


def test_ollama_state_reads_version_and_loaded_processors(monkeypatch):
    import httpx
    from techdocqa.evaluation.runtime import ollama_state, processor_split, summary_line
    real = httpx.Client
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.16"})
        return httpx.Response(200, json={"models": [{"name": "qwen3:1.7b", "size": 200, "size_vram": 100},
                                                    {"name": "nomic-embed-text:latest", "size": 600, "size_vram": 0}]})
    monkeypatch.delenv("TECHDOCQA_OFFLINE")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    state = ollama_state("http://127.0.0.1:11434")
    assert state["version"] == "0.40.16"
    assert [(item["model"], item["processor"]) for item in state["loaded"]] == [("nomic-embed-text:latest", "100% CPU"),
                                                                                ("qwen3:1.7b", "50%/50% CPU/GPU")]
    assert processor_split(10, 10) == "100% GPU" and processor_split(0, 0) == "unknown"
    def refused(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(refused), **kwargs))
    assert ollama_state("http://127.0.0.1:11434") == {"version": None, "loaded": None, "note": "unreachable"}
    # Reports from before Phase 11 have no runtime record and are re-rendered by --record-review.
    assert summary_line({"code": {}}) == "- Runtime: not recorded (run before Phase 11)"


def test_private_documents_outside_the_manifest_never_appear(bench, model_settings, registry):
    report = run(bench, model_settings, registry)
    private = {chunk["chunk_id"] for chunk in active_chunks(bench["versions"]["private.md"].version_id, model_settings, registry)}
    ranked = {chunk for item in report["questions"] for row in item["results"].values() for chunk in row["ranked"]}
    assert ranked and not ranked & private


def test_identical_inputs_give_identical_metrics(bench, model_settings, registry):
    first, second = run(bench, model_settings, registry), run(bench, model_settings, registry)
    assert first["run_id"] != second["run_id"]
    assert first["results_fingerprint"] == second["results_fingerprint"]
    # Everything but the timings repeats.
    strip = lambda rows: [{k: v for k, v in row.items() if k not in ("duration_seconds", "latency_seconds")} for row in rows]
    assert strip(first["configurations"]) == strip(second["configurations"])


def test_fingerprint_covers_only_the_p0_summary(bench, model_settings, registry):
    report = run(bench, model_settings, registry)
    for row in report["configurations"]:
        kept = fingerprinted(row)
        assert set(kept) <= set(P0_SUMMARY_KEYS) and "latency_seconds" not in kept and "duration_seconds" not in kept
        assert tuple(kept["metrics"]) == P0_METRICS
        assert all(set(values) == {"questions", *P0_METRICS} for values in kept["by_technology"].values())
    parts = report["dataset"]["sha256"], report["corpus"]["corpus_fingerprint"]
    assert results_fingerprint(*parts, report["configurations"], report["questions"]) == report["results_fingerprint"]
    # P1 metrics, latency and comparisons are derived from fingerprinted ranks, so changing them moves nothing...
    altered = json.loads(json.dumps(report["configurations"]))
    for row in altered:
        row["metrics"]["ndcg@5"] = row["by_technology"]["Kafka"]["precision@3"] = 0.123
        row["latency_seconds"]["p95"] = 99.0
    assert results_fingerprint(*parts, altered, report["questions"]) == report["results_fingerprint"]
    # ...while any P0 metric does.
    altered[0]["metrics"]["recall@5"] = 0.123
    assert results_fingerprint(*parts, altered, report["questions"]) != report["results_fingerprint"]


def test_comparisons_pair_questions_evaluated_in_both(bench, model_settings, registry):
    report = run(bench, model_settings, registry)
    [entry] = report["comparisons"]
    assert (entry["candidate"], entry["baseline"], entry["questions"]) == ("vector", "bm25", 3)
    assert set(entry["metrics"]) == {"ndcg@5", "recall@5", "mrr"} and "benefit_rule" not in entry
    by_id = {item["id"]: item["results"] for item in report["questions"]}
    expected = sum(by_id[name]["vector"]["metrics"]["ndcg@5"] - by_id[name]["bm25"]["metrics"]["ndcg@5"]
                   for name in ("kafka-1", "kafka-2", "redis-1")) / 3
    assert entry["metrics"]["ndcg@5"]["mean_difference"] == pytest.approx(expected, abs=1e-6)
    assert entry["metrics"]["ndcg@5"]["interval"][0] <= entry["metrics"]["ndcg@5"]["interval"][1]
    assert "## Paired differences" in render_markdown(report) and "| vector | bm25 | 3 | ndcg@5 |" in render_markdown(report)
    assert run(bench, model_settings, registry, modes=["bm25"])["comparisons"] == []


def test_four_configurations_run_and_reranking_without_a_reranker_is_reported(bench, model_settings, registry):
    report = run(bench, model_settings, registry, modes=["bm25", "vector", "hybrid", "hybrid+rerank"])
    statuses = {row["mode"]: (row["status"], row.get("error", {}).get("code")) for row in report["configurations"]}
    assert statuses == {"bm25": ("completed", None), "vector": ("completed", None),
                        "hybrid": ("completed", None), "hybrid+rerank": ("failed", "RERANKER_NOT_CONFIGURED")}
    assert [(entry["candidate"], entry["baseline"]) for entry in report["comparisons"]] == [("vector", "bm25"), ("hybrid", "vector")]
    rule = report["comparisons"][1]["benefit_rule"]
    assert set(rule) == {"interval_above_zero", "p95_latency_seconds", "latency_within_limit", "measured_benefit"}
    assert "| hybrid+rerank | failed: RERANKER_NOT_CONFIGURED |" in render_markdown(report)
    with pytest.raises(TechDocQAError) as caught:
        run(bench, model_settings, registry, modes=["reranked"])
    assert caught.value.response.error.code == "INVALID_ARGUMENT"


def test_questions_outside_the_calibration_set_are_held_out_and_get_no_adoptable_proposal(bench, model_settings, registry):
    """P10-8: thresholds come from the smoke file beside the manifest; a run with other questions only describes them."""
    lines = bench["dataset"].read_text(encoding="utf-8").splitlines(keepends=True)
    calibration = bench["manifest"].parent / "benchmark_smoke.jsonl"
    calibration.write_text("".join(lines[:2]), encoding="utf-8")
    report = run(bench, model_settings, registry, modes=["bm25"])
    assert report["dataset"]["calibration"] == {"dataset_id": "benchmark_smoke", "sha256": load_dataset(calibration).sha256,
                                                "calibration_questions": 2, "held_out": 2}
    assert any("2 are held out" in note for note in report["notes"])
    assert not any("not an independent holdout" in note for note in report["notes"])
    markdown = render_markdown(report)
    assert "descriptive, not for adoption" in markdown and "```toml" not in markdown
    calibration.write_text("".join(lines), encoding="utf-8")
    report = run(bench, model_settings, registry, modes=["bm25"])
    assert report["dataset"]["calibration"]["held_out"] == 0 and "```toml" in render_markdown(report)
    assert any("not an independent holdout" in note for note in report["notes"])


def test_unanswerable_questions_get_score_spreads_not_recall(bench, model_settings, registry):
    report = run(bench, model_settings, registry, modes=["bm25"])
    row = next(item for item in report["questions"] if item["id"] == "ood-1")["results"]["bm25"]
    assert "metrics" not in row and "first_relevant_rank" not in row
    assert report["configurations"][0]["unanswerable"]["questions"] == 1


# Lifecycle flags (AC-21.3)

def test_deleted_source_flags_its_questions_and_leaves_the_benchmark_unchanged(bench, model_settings, registry):
    before = bench["dataset"].read_bytes()
    delete_document(bench["versions"]["redis.md"].document_id, "Licence ended", model_settings, registry)
    report = run(bench, model_settings, registry)
    assert report["flags"] == [{"question": "redis-1", "item": "redis-1#0", "source_key": bench["keys"]["redis.md"], "reason": "SOURCE_DELETED"}]
    assert all(row["excluded_questions"] == 1 and row["evaluated_questions"] == 2 for row in report["configurations"])
    assert bench["dataset"].read_bytes() == before and report["dataset"]["sha256"] == load_dataset(bench["dataset"]).sha256
    assert report["corpus"]["unavailable"] == {bench["keys"]["redis.md"]: "SOURCE_DELETED"}
    assert "redis-1: SOURCE_DELETED" in render_markdown(report)


def test_withdrawn_out_of_scope_and_unresolved_labels_are_flagged(bench, model_settings, registry, tmp_path):
    withdraw_document(bench["versions"]["redis.md"].document_id, "Review", registry)
    dataset = write_lines(tmp_path / "flags.jsonl", [
        question("gone", "Redis?", {"source_key": bench["keys"]["redis.md"], "anchor": "evicts them"}),
        question("private", "Notes?", {"source_key": bench["keys"]["private.md"], "anchor": "private notes"}),
        question("moved", "Kafka?", {"source_key": bench["keys"]["kafka.md"], "anchor": "text that is not there"}),
        question("fine", "Kafka?", {"source_key": bench["keys"]["kafka.md"], "anchor": "replicate partitions"}),
    ])
    report = run_evaluation(dataset, bench["manifest"], model_settings, registry, modes=["bm25"])
    assert {flag["question"]: flag["reason"] for flag in report["flags"]} == {
        "gone": "SOURCE_NOT_ACTIVE", "private": "SOURCE_OUT_OF_SCOPE", "moved": "ANCHOR_UNRESOLVED"}
    assert report["configurations"][0]["evaluated_questions"] == 1 and report["configurations"][0]["excluded_questions"] == 3


# Failures and CLI (FR-22 eval slice)

def test_failed_vector_provider_is_reported_and_bm25_still_runs(bench, model_settings, registry, embedder):
    embedder.fail = True
    report = run(bench, model_settings, registry)
    bm25, vector = report["configurations"]
    assert bm25["status"] == "completed" and bm25["metrics"]["recall@5"] is not None
    assert vector["status"] == "failed" and vector["error"]["code"] == "EMBEDDING_PROVIDER_UNAVAILABLE"
    assert "secret provider detail" not in json.dumps(report)
    assert "failed: EMBEDDING_PROVIDER_UNAVAILABLE" in render_markdown(report)


def test_eval_cli_writes_json_and_markdown_reports(bench, model_settings, registry, embedder, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("techdocqa.cli.load_settings", lambda *_: model_settings)
    capsys.readouterr()
    out = tmp_path / "reports"
    assert main(["eval", "--dataset", str(bench["dataset"]), "--manifest", str(bench["manifest"]), "--report-dir", str(out)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "questions" not in payload and payload["run_id"].startswith("eval_")
    saved = json.loads(Path(payload["report_files"]["json"]).read_text(encoding="utf-8"))
    assert saved["results_fingerprint"] == payload["results_fingerprint"] and len(saved["questions"]) == 4
    assert "| bm25 |" in Path(payload["report_files"]["markdown"]).read_text(encoding="utf-8")
    assert main(["eval", "--mode", "bm25", "--dataset", str(bench["dataset"]), "--manifest", str(bench["manifest"]),
                 "--report-dir", str(out)]) == 0
    assert [row["mode"] for row in json.loads(capsys.readouterr().out)["configurations"]] == ["bm25"]
    embedder.fail = True
    assert main(["eval", "--dataset", str(bench["dataset"]), "--manifest", str(bench["manifest"]), "--report-dir", str(out)]) == 1
    capsys.readouterr()
    bad = write_lines(tmp_path / "bad.jsonl", [question("q", "No items?")])
    assert main(["eval", "--dataset", str(bad), "--manifest", str(bench["manifest"])]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "INVALID_BENCHMARK"
    assert main(["eval", "--mode", "reranked"]) == 2


def test_help_lists_eval(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "eval" in capsys.readouterr().out
