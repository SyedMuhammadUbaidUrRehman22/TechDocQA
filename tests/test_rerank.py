"""FR-15 reranking (AC-15.1 to AC-15.5) behind one interface, with a mocked reranker and its call log (P10-4, P10-5)."""

import hashlib
import json
import math
from pathlib import Path

import pytest

from techdocqa.answering import sufficiency
from techdocqa.answering.generation import answer_question
from techdocqa.cli import answer_configuration, main
from techdocqa.errors import TechDocQAError
from techdocqa.evaluation.runner import render_markdown, run_evaluation
from techdocqa.indexing import embeddings
from techdocqa.retrieval import cross_encoder, rerank
from techdocqa.retrieval.search import retrieval_config_id, search
from techdocqa.schemas import SearchRequest
from techdocqa.settings import HybridThresholds, SufficiencyLevels, SufficiencyThresholds, load_settings
# Shared fixtures: inline workers, the counting embedder, a verified profile, an indexed corpus, a scripted chat model.
from test_evaluation import bench  # noqa: F401
from test_generation import chat, qa_settings  # noqa: F401
from test_indexing import embedder, indexed, inline_workers, model_settings  # noqa: F401

KAFKA = "How do Kafka brokers replicate partitions?"
ROOT = Path(__file__).resolve().parents[1]


class MockReranker:
    """Scores texts by a function of the query and texts (by default, their position), and logs how many each call sent."""

    def __init__(self, scores=None, fail=None):
        self.scores = scores or (lambda query, texts: [float(index) for index in range(len(texts))])
        self.fail = fail
        self.calls = []

    def score(self, query, texts):
        self.calls.append(len(texts))
        if self.fail is not None:
            raise self.fail
        return self.scores(query, texts)


@pytest.fixture
def reranker(model_settings, monkeypatch):
    model_settings.retrieval.reranker.model = "mock-cross-encoder"
    model_settings.retrieval.reranker.revision = "r1"
    fake = MockReranker()
    monkeypatch.setattr(rerank, "build_reranker", lambda settings: fake)
    return fake


def query(settings, registry, mode="hybrid", top_k=5, rerank=False, text=KAFKA):
    return search(SearchRequest(query=text, mode=mode, top_k=top_k, rerank=rerank), settings, registry)


def ids(response):
    return [result.chunk_id for result in response.results]


# AC-15.1 and FR-15.5

def test_output_follows_the_mocked_reranker_scores_and_keeps_earlier_scores(indexed, model_settings, registry, reranker):
    candidates = query(model_settings, registry, top_k=20)
    response = query(model_settings, registry, rerank=True)
    # The mock scores candidates 0, 1, 2, ... in input order, so the reranked order is the input reversed.
    assert ids(response) == list(reversed(ids(candidates)))[:5]
    assert response.reranked and not response.degraded and response.mode == "hybrid"
    raw = [result.scores["rerank"] for result in response.results]
    assert raw == sorted(raw, reverse=True) == [float(index) for index in range(len(candidates.results) - 1, len(candidates.results) - 6, -1)]
    before = {result.chunk_id: result for result in candidates.results}
    for rank, result in enumerate(response.results, 1):
        earlier = before[result.chunk_id]
        assert result.rank == result.ranks["rerank"] == rank
        assert result.relevance == pytest.approx(1 / (1 + math.exp(-result.scores["rerank"])))
        # Source metadata, earlier ranks, scores and component relevances are kept beside the reranker's (FR-15.5).
        assert (result.document_id, result.version_id, result.text) == (earlier.document_id, earlier.version_id, earlier.text)
        assert {key: value for key, value in result.ranks.items() if key != "rerank"} == earlier.ranks
        assert {key: value for key, value in result.scores.items() if key != "rerank"} == earlier.scores
        assert result.relevances == {**earlier.relevances, "rerank": result.relevance}


def test_equal_reranker_scores_keep_the_input_order(indexed, model_settings, registry, reranker):
    reranker.scores = lambda query, texts: [1.0] * len(texts)
    assert ids(query(model_settings, registry, rerank=True)) == ids(query(model_settings, registry))


def test_every_mode_can_be_reranked(indexed, model_settings, registry, reranker):
    for mode in ("bm25", "vector"):
        candidates = query(model_settings, registry, mode=mode, top_k=20)
        response = query(model_settings, registry, mode=mode, rerank=True)
        assert response.reranked and ids(response) == list(reversed(ids(candidates)))[:5]
        top = response.results[0]
        assert set(top.relevances) == {mode, "rerank"} and top.relevances[mode] == next(
            result.relevance for result in candidates.results if result.chunk_id == top.chunk_id)


# AC-15.2

def test_disabled_reranking_returns_the_input_order_truncated(indexed, model_settings, registry, reranker):
    for mode in ("bm25", "vector", "hybrid"):
        response = query(model_settings, registry, mode=mode)
        assert not response.reranked and ids(response) == ids(query(model_settings, registry, mode=mode, top_k=20))[:5]
        assert all("rerank" not in result.scores for result in response.results)
    assert reranker.calls == []


# AC-15.3

def test_at_most_the_configured_maximum_is_sent(indexed, model_settings, registry, reranker):
    candidates = ids(query(model_settings, registry, top_k=20))
    assert len(candidates) > 3
    query(model_settings, registry, rerank=True)
    assert reranker.calls == [min(len(candidates), 20)]
    model_settings.retrieval.rerank_max_candidates = 3
    response = query(model_settings, registry, rerank=True, top_k=2)
    # Only the first three candidates are reranked; the ones beyond the maximum are dropped from reranking.
    assert reranker.calls[-1] == 3 and ids(response) == list(reversed(candidates[:3]))[:2]
    # A request for more than the maximum gets at most the maximum (FR-15.1 and FR-15.2).
    assert len(query(model_settings, registry, rerank=True, top_k=5).results) == 3 and reranker.calls[-1] == 3


# AC-15.4

@pytest.mark.parametrize("failure, code", [
    (RuntimeError("secret runtime detail"), "RERANKER_FAILED"),
    (TechDocQAError("RERANKER_UNAVAILABLE", "The configured reranker is not installed.", stage="rerank"), "RERANKER_UNAVAILABLE"),
])
def test_a_reranker_exception_falls_back_to_the_unreranked_order(indexed, model_settings, registry, reranker, failure, code):
    reranker.fail = failure
    response = query(model_settings, registry, rerank=True)
    assert response.degraded and not response.reranked and response.rerank_failure == response.degradation_reason == code
    assert response.failed_retriever is None
    assert ids(response) == ids(query(model_settings, registry)) and "secret runtime detail" not in response.model_dump_json()


@pytest.mark.parametrize("scores", [lambda query, texts: [1.0], lambda query, texts: [math.nan] * len(texts)])
def test_an_invalid_score_list_is_a_reranker_failure(indexed, model_settings, registry, reranker, scores):
    reranker.scores = scores
    response = query(model_settings, registry, rerank=True)
    assert response.rerank_failure == "RERANKER_FAILED" and ids(response) == ids(query(model_settings, registry))


def test_reranking_needs_a_configured_reranker_with_pinned_files(indexed, model_settings, registry):
    with pytest.raises(TechDocQAError) as caught:
        query(model_settings, registry, rerank=True)
    assert (caught.value.response.error.code, caught.value.response.error.stage) == ("RERANKER_NOT_CONFIGURED", "configuration")
    model_settings.retrieval.reranker.model = "configured-but-absent"
    response = query(model_settings, registry, rerank=True)
    assert response.degraded and response.rerank_failure == "RERANKER_UNAVAILABLE"


def test_a_retriever_failure_and_reranking_are_both_reported(indexed, model_settings, registry, reranker, embedder):
    embedder.fail = True
    response = query(model_settings, registry, rerank=True)
    assert response.reranked and response.degraded and response.failed_retriever == "vector"
    assert response.degradation_reason == "EMBEDDING_PROVIDER_UNAVAILABLE" and response.rerank_failure is None


def test_sigmoid_is_the_documented_map():
    assert rerank.sigmoid(0.0) == 0.5 and rerank.sigmoid(2.0) == pytest.approx(0.880797, abs=1e-6)
    assert rerank.sigmoid(-1000.0) == 0.0 and rerank.sigmoid(1000.0) == 1.0


# Configuration identity (P10-4)

def test_only_reranked_requests_carry_the_reranker_identity(indexed, model_settings, registry, reranker):
    profile = embeddings.embedding_profile(model_settings.model)
    def config_id(mode, rerank_on):
        return retrieval_config_id(SearchRequest(query="x", mode=mode, rerank=rerank_on), model_settings, None if mode == "bm25" else profile)
    plain = {mode: config_id(mode, False) for mode in ("bm25", "vector", "hybrid")}
    reranked = config_id("hybrid", True)
    assert reranked not in plain.values()
    model_settings.retrieval.reranker.revision = "r2"
    assert {mode: config_id(mode, False) for mode in ("bm25", "vector", "hybrid")} == plain and config_id("hybrid", True) != reranked
    # The reranker scale is bound to the base mode whose candidates it was calibrated on.
    assert sufficiency.rerank_scoring_config_id("hybrid", model_settings) != sufficiency.rerank_scoring_config_id("bm25", model_settings)


# The FR-18 gate with reranking

def reranked_thresholds(settings, value, base="hybrid"):
    return SufficiencyThresholds(min_top_score=value, min_chunk_score=value, calibration_run_id="eval_test",
                                 scoring_config_id=sufficiency.rerank_scoring_config_id(base, settings))


def test_ask_with_reranking_is_judged_on_the_reranker_scale(indexed, qa_settings, registry, chat, reranker):
    qa_settings.retrieval.sufficiency.reranked = reranked_thresholds(qa_settings, 0.999999)
    refused = answer_question(KAFKA, qa_settings, registry, mode="hybrid", rerank=True)
    assert (refused.status, refused.reason, refused.reranked, refused.llm_called) == ("no_evidence", "LOW_RELEVANCE", True, False)
    gate = refused.sufficiency
    assert gate.thresholds_from == "reranked" and gate.relevance_policy == rerank.RERANK_POLICY and gate.min_top_score == 0.999999
    qa_settings.retrieval.sufficiency.reranked = reranked_thresholds(qa_settings, 0.5)
    assert answer_question(KAFKA, qa_settings, registry, mode="hybrid", rerank=True).status == "answered"
    # Reranking follows the configuration unless the request says otherwise.
    qa_settings.retrieval.rerank = True
    assert answer_question(KAFKA, qa_settings, registry, mode="hybrid").reranked
    assert not answer_question(KAFKA, qa_settings, registry, mode="hybrid", rerank=False).reranked


def test_a_reranker_failure_falls_back_to_the_hybrid_gate(indexed, qa_settings, registry, chat, reranker):
    profile = embeddings.embedding_profile(qa_settings.model)
    from techdocqa.retrieval.search import scoring_config_id
    qa_settings.retrieval.sufficiency.reranked = reranked_thresholds(qa_settings, 0.01)
    qa_settings.retrieval.sufficiency.hybrid = HybridThresholds(
        gate="vector", vector=SufficiencyLevels(min_top_score=0.99, min_chunk_score=0.99), calibration_run_id="eval_test",
        scoring_config_id=scoring_config_id("hybrid", qa_settings, profile))
    reranker.fail = RuntimeError("down")
    response = answer_question(KAFKA, qa_settings, registry, mode="hybrid", rerank=True)
    assert response.degraded and response.degradation_reason == "RERANKER_FAILED" and not response.reranked
    assert (response.status, response.reason) == ("no_evidence", "LOW_RELEVANCE") and chat.prompts == []
    assert response.sufficiency.gate == "vector" and response.sufficiency.thresholds_from is None
    assert "SEARCH_DEGRADED" in {warning.code for warning in response.warnings}


def test_reranker_thresholds_from_hybrid_candidates_do_not_judge_another_mode(indexed, qa_settings, registry, chat, reranker):
    qa_settings.retrieval.sufficiency.reranked = reranked_thresholds(qa_settings, 0.999999, base="hybrid")
    response = answer_question(KAFKA, qa_settings, registry, mode="bm25", rerank=True)
    assert response.status == "answered" and sufficiency.STALE in {warning.code for warning in response.warnings}
    assert response.sufficiency.calibrated is False


# Evaluation and the CLI (AC-15.5)

def test_the_report_lists_hybrid_with_and_without_reranking(bench, model_settings, registry, reranker):
    # Query-word overlap, so the questions' top scores differ and a threshold can be proposed.
    reranker.scores = lambda query, texts: [float(len(set(query.casefold().split()) & set(text.casefold().split()))) - 2
                                            for text in texts]
    report = run_evaluation(bench["dataset"], bench["manifest"], model_settings, registry, modes=["vector", "hybrid", "hybrid+rerank"])
    rows = {row["mode"]: row for row in report["configurations"]}
    assert rows["hybrid"]["status"] == rows["hybrid+rerank"]["status"] == "completed"
    assert rows["hybrid"]["retrieval_config_id"] != rows["hybrid+rerank"]["retrieval_config_id"]
    calibration = rows["hybrid+rerank"]["refusal_calibration"]
    assert calibration["section"] == "reranked" and calibration["relevance_policy"] == rerank.RERANK_POLICY
    assert calibration["proposed"] is not None and calibration["active"]["status"] == "not_calibrated"
    row = next(item for item in report["questions"] if item["id"] == "kafka-1")["results"]["hybrid+rerank"]
    assert row["scores"] == sorted(row["scores"], reverse=True) and all(0 < value < 1 for value in row["relevance"])
    assert [(entry["candidate"], entry["baseline"]) for entry in report["comparisons"]] == [("hybrid", "vector"), ("hybrid+rerank", "hybrid")]
    markdown = render_markdown(report)
    assert "| hybrid |" in markdown and "| hybrid+rerank |" in markdown and "[retrieval.sufficiency.reranked]" in markdown


def test_a_reranker_failure_fails_the_reranked_configuration(bench, model_settings, registry, reranker):
    reranker.fail = RuntimeError("down")
    report = run_evaluation(bench["dataset"], bench["manifest"], model_settings, registry, modes=["hybrid", "hybrid+rerank"])
    hybrid, reranked = report["configurations"]
    assert hybrid["status"] == "completed" and reranked["status"] == "failed" and reranked["error"]["code"] == "SEARCH_DEGRADED"
    assert "reranker RERANKER_FAILED" in reranked["error"]["message"]


def test_cli_switches_reranking_per_request(indexed, model_settings, registry, monkeypatch, capsys, reranker):
    monkeypatch.setattr("techdocqa.cli.load_settings", lambda *_: model_settings)
    capsys.readouterr()
    assert main(["search", KAFKA, "--mode", "hybrid", "--rerank"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reranked"] and "rerank" in payload["results"][0]["scores"]
    model_settings.retrieval.rerank = True
    assert main(["search", KAFKA, "--mode", "hybrid", "--no-rerank"]) == 0
    assert json.loads(capsys.readouterr().out)["reranked"] is False
    assert main(["search", KAFKA, "--mode", "hybrid"]) == 0
    assert json.loads(capsys.readouterr().out)["reranked"] is True
    model_settings.retrieval.reranker.model = None
    assert main(["search", KAFKA, "--rerank"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "RERANKER_NOT_CONFIGURED"


def test_answer_runs_take_hybrid_with_reranking_as_a_configuration():
    class Args:
        mode = None
    assert answer_configuration(Args) == {"mode": None, "rerank": None}
    Args.mode = ["hybrid+rerank"]
    assert answer_configuration(Args) == {"mode": "hybrid", "rerank": True}
    Args.mode = ["vector"]
    assert answer_configuration(Args) == {"mode": "vector", "rerank": None}


# P10-5: the local cross-encoder, with its files pinned by hash

def fake_model(directory, max_position=512):
    """Stand-in files with their real hashes; only the hash and position checks read them."""
    (directory / "onnx").mkdir(parents=True)
    contents = {cross_encoder.MODEL_FILE: b"model", cross_encoder.TOKENIZER_FILE: b"{}",
                cross_encoder.CONFIG_FILE: json.dumps({"max_position_embeddings": max_position}).encode()}
    for name, data in contents.items():
        (directory / name).write_bytes(data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}


def unavailable(directory, files, max_length=512):
    with pytest.raises(TechDocQAError) as caught:
        cross_encoder.OnnxCrossEncoder(directory, files, max_length)
    return caught.value.response.error.code, caught.value.response.error.stage


def test_the_cross_encoder_refuses_unpinned_altered_or_missing_files(tmp_path):
    files = fake_model(tmp_path / "model")
    assert unavailable(tmp_path / "model", {**files, cross_encoder.MODEL_FILE: "0" * 64}) == ("RERANKER_UNAVAILABLE", "rerank")
    assert unavailable(tmp_path / "model", {cross_encoder.TOKENIZER_FILE: files[cross_encoder.TOKENIZER_FILE]})[0] == "RERANKER_UNAVAILABLE"
    assert unavailable(tmp_path / "elsewhere", files)[0] == "RERANKER_UNAVAILABLE"
    # A pinned extra file is checked too.
    assert unavailable(tmp_path / "model", {**files, "README.md": "0" * 64})[0] == "RERANKER_UNAVAILABLE"


def test_max_length_cannot_exceed_the_models_position_limit(tmp_path):
    files = fake_model(tmp_path / "model", max_position=256)
    assert unavailable(tmp_path / "model", files, max_length=512)[0] == "RERANKER_UNAVAILABLE"


def test_the_model_directory_comes_from_the_data_directory_model_and_revision(model_settings):
    model_settings.retrieval.reranker.model, model_settings.retrieval.reranker.revision = "org/name", "abc"
    assert cross_encoder.model_directory(model_settings) == Path(model_settings.data_directory) / "models" / "org--name" / "abc"
    model_settings.retrieval.reranker.revision = None
    with pytest.raises(TechDocQAError) as caught:
        cross_encoder.from_settings(model_settings)
    assert caught.value.response.error.code == "RERANKER_UNAVAILABLE"


def test_altered_reranker_files_degrade_search_to_the_unreranked_order(indexed, model_settings, registry):
    reranker = model_settings.retrieval.reranker
    reranker.model, reranker.revision = "org/name", "abc"
    reranker.files_sha256 = {name: "0" * 64 for name in cross_encoder.REQUIRED_FILES}
    fake_model(cross_encoder.model_directory(model_settings))
    response = query(model_settings, registry, rerank=True)
    assert response.degraded and response.rerank_failure == "RERANKER_UNAVAILABLE" and not response.reranked
    assert ids(response) == ids(query(model_settings, registry))


PINNED = load_settings(ROOT / "config" / "default.toml").retrieval.reranker
PINNED_DIRECTORY = ROOT / "data" / "models" / str(PINNED.model).replace("/", "--") / str(PINNED.revision)


@pytest.mark.skipif(not PINNED.model or not PINNED_DIRECTORY.is_dir(), reason="the pinned reranker model is not downloaded")
def test_the_pinned_cross_encoder_reproduces_its_model_card_and_repeats_exactly():
    model = cross_encoder.load(str(PINNED_DIRECTORY), tuple(sorted(PINNED.files_sha256.items())), PINNED.max_length)
    berlin = ["Berlin had a population of 3,520,031 registered inhabitants in an area of 891.82 square kilometers.",
              "Berlin is well known for its museums."]
    scores = model.score("How many people live in Berlin?", berlin)
    # The model card's scores, from sentence-transformers on PyTorch.
    assert scores[0] == pytest.approx(8.607138, abs=1e-3) and scores[1] == pytest.approx(-4.320078, abs=1e-3)
    assert model.score("How many people live in Berlin?", berlin) == scores
    # A pair's score does not depend on the other texts sent with it.
    assert model.score("How many people live in Berlin?", berlin[1:]) == scores[1:]
    # A 1,000-character query still fits within max_length with a long chunk.
    assert len(model.score("why " * 250, [" ".join(berlin) * 10])) == 1
