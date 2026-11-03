"""FR-19 smoke slice, AC-21.3 deletion flags and the eval CLI, offline with the counting fake embedder."""

import json
from pathlib import Path

import pytest

from techdocqa.cli import main
from techdocqa.errors import TechDocQAError
from techdocqa.evaluation.dataset import load_dataset
from techdocqa.evaluation.metrics import macro_average, question_metrics, recall_at_k, reciprocal_rank
from techdocqa.evaluation.runner import render_markdown, run_evaluation
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
    # Ranks: miss, a, miss, b, a again.
    matches = [set(), {"a"}, set(), {"b"}, {"a"}]
    values = question_metrics(matches, {"a", "b"})
    assert values == {"recall@1": 0.0, "recall@3": 0.5, "recall@5": 1.0, "mrr": 0.5}
    # The requirement's example: first relevant result at rank 2 gives MRR 0.5.
    assert reciprocal_rank([set(), {"x"}], {"x"}) == 0.5
    assert reciprocal_rank([{"x"}], {"x"}) == 1.0
    assert reciprocal_rank([set(), set(), {"x"}], {"x"}) == pytest.approx(1 / 3)
    assert question_metrics([set()] * 5, {"x"}) == {"recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0, "mrr": 0.0}


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
    assert macro_average(rows) == {"recall@1": 0.5, "recall@3": 0.75, "recall@5": 1.0, "mrr": 0.625}
    assert macro_average([]) == {"recall@1": None, "recall@3": None, "recall@5": None, "mrr": None}


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


# Runs (AC-19.1, AC-19.4)

def test_run_reports_both_modes_with_dataset_corpus_and_configuration_identity(bench, model_settings, registry):
    report = run(bench, model_settings, registry)
    assert [row["mode"] for row in report["configurations"]] == ["bm25", "vector"]
    for row in report["configurations"]:
        assert row["status"] == "completed" and row["retrieval_config_id"].startswith("rc_")
        assert row["evaluated_questions"] == 3 and row["excluded_questions"] == 0
        assert set(row["metrics"]) == {"recall@1", "recall@3", "recall@5", "mrr"}
        assert all(0 <= value <= 1 for value in row["metrics"].values())
        assert set(row["by_technology"]) == {"Kafka", "Redis"}
    assert report["dataset"]["sha256"] == load_dataset(bench["dataset"]).sha256 and report["dataset"]["draft"] == 4
    assert report["corpus"]["searchable_documents"] == 2 and report["corpus"]["excluded_eligible_documents"] == 1
    assert len(report["corpus"]["corpus_fingerprint"]) == 64 and report["within_time_limit"]
    assert report["environment"]["embedding"]["digest"] == "a" * 64 and report["environment"]["libraries"]["pydantic"]
    assert report["flags"] == [] and any("drafts without second-person review" in note for note in report["notes"])
    by_id = {item["id"]: item for item in report["questions"]}
    # Whitespace and case in an anchor do not matter; a section label matches every chunk under it.
    assert by_id["kafka-1"]["items"][0]["resolved_chunks"] >= 1 and by_id["kafka-2"]["items"][0]["resolved_chunks"] >= 1
    assert by_id["kafka-1"]["results"]["bm25"]["first_relevant_rank"] == 1


def test_private_documents_outside_the_manifest_never_appear(bench, model_settings, registry):
    report = run(bench, model_settings, registry)
    private = {chunk["chunk_id"] for chunk in active_chunks(bench["versions"]["private.md"].version_id, model_settings, registry)}
    ranked = {chunk for item in report["questions"] for row in item["results"].values() for chunk in row["ranked"]}
    assert ranked and not ranked & private


def test_identical_inputs_give_identical_metrics(bench, model_settings, registry):
    first, second = run(bench, model_settings, registry), run(bench, model_settings, registry)
    assert first["run_id"] != second["run_id"]
    assert first["results_fingerprint"] == second["results_fingerprint"]
    strip = lambda rows: [{k: v for k, v in row.items() if k != "duration_seconds"} for row in rows]
    assert strip(first["configurations"]) == strip(second["configurations"])


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
    assert main(["eval", "--mode", "hybrid"]) == 2


def test_help_lists_eval(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "eval" in capsys.readouterr().out
