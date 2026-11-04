"""FR-18 calibrated sufficiency, its Q-07 score scales and calibration, AC-21.1 and the refusal run, offline.

A scripted chat model records every prompt, so "no LLM call" is checked by its call count, not inferred.
"""

import json
import math
from pathlib import Path

import pytest

from techdocqa.answering import generation, sufficiency
from techdocqa.answering.sufficiency import choose, leave_one_out_errors, propose
from techdocqa.cli import main
from techdocqa.evaluation.runner import render_markdown, run_evaluation
from techdocqa.indexing.embeddings import embedding_profile
from techdocqa.indexing.lifecycle import withdraw_document
from techdocqa.retrieval.lexical import LexicalIndex
from techdocqa.retrieval.search import scoring_config_id, search
from techdocqa.schemas import SearchRequest
from techdocqa.settings import SufficiencyThresholds, load_settings
# Shared fixtures: inline workers, the counting embedder, an indexed corpus, the smoke-benchmark stand-in and the scripted chat.
from test_evaluation import bench  # noqa: F401
from test_generation import ask, chat, log_lines, qa_settings, write_config  # noqa: F401
from test_indexing import embedder, indexed, inline_workers, model_settings  # noqa: F401

QUESTION = "How do Kafka brokers replicate partitions?"


def profile_for(settings, mode):
    return embedding_profile(settings.model) if mode == "vector" else None


def calibrate(settings, mode, threshold, *, chunk=None, supporting=1, run_id="eval_test", scoring=None):
    thresholds = SufficiencyThresholds(min_top_score=threshold, min_chunk_score=threshold if chunk is None else chunk,
                                       min_supporting_chunks=supporting, calibration_run_id=run_id,
                                       scoring_config_id=scoring or scoring_config_id(mode, settings, profile_for(settings, mode)))
    setattr(settings.retrieval.sufficiency, mode, thresholds)
    return thresholds


def top_relevance(settings, registry, text=QUESTION, mode="bm25"):
    return search(SearchRequest(query=text, mode=mode, top_k=5), settings, registry).results[0].relevance


def codes(response):
    return {warning.code for warning in response.warnings}


# Q-07 score scales

def test_bm25_relevance_is_the_raw_score_over_the_query_ceiling():
    chunks = [{"chunk_id": f"c{i}", "text": text} for i, text in enumerate(["alpha beta", "beta gamma delta", "gamma", "delta"])]
    k1, b = 1.5, 0.5
    index = LexicalIndex(chunks, k1, b)
    idf = math.log(4 - 1 + 0.5) - math.log(1 + 0.5)
    raw = idf * (k1 + 1) / (1 + k1 * (1 - b + b * 2 / ((2 + 3 + 1 + 1) / 4)))
    (top, score, relevance), = index.search("alpha", 1)
    assert top["chunk_id"] == "c0" and score == pytest.approx(raw) and relevance == pytest.approx(raw / ((k1 + 1) * idf))
    # A word the corpus lacks adds nothing to the score but counts at the unseen-term IDF in the ceiling.
    unseen = math.log(4 + 0.5) - math.log(0.5)
    (_, same_score, lower), = index.search("alpha zeta", 1)
    assert same_score == pytest.approx(raw) and lower == pytest.approx(raw / ((k1 + 1) * (idf + unseen))) and lower < relevance


def test_relevance_keeps_each_ranking_and_stays_on_a_zero_to_one_scale(indexed, model_settings, registry):
    for mode in ("bm25", "vector"):
        results = search(SearchRequest(query="Kafka brokers keys memory", mode=mode, top_k=5), model_settings, registry).results
        assert len(results) > 1 and all(0 <= result.relevance <= 1 for result in results)
        assert [result.relevance for result in results] == sorted((result.relevance for result in results), reverse=True)
    vector = search(SearchRequest(query="Kafka brokers", mode="vector", top_k=5), model_settings, registry).results
    assert all(result.relevance == result.scores["vector"] for result in vector)


# Calibration rule

def test_separable_scores_put_the_threshold_in_the_middle_of_the_gap():
    proposal = propose([0.9, 0.88, 0.95], [0.8, 0.83])
    assert proposal["min_top_score"] == pytest.approx(0.855) and proposal["min_chunk_score"] == proposal["min_top_score"]
    assert proposal["margin"] == pytest.approx(0.025) and proposal["separable"] and proposal["min_supporting_chunks"] == 1
    assert (proposal["answerable_passed"], proposal["unanswerable_refused"], proposal["leave_one_out_errors"]) == (3, 2, 0)


def test_overlapping_scores_maximize_balanced_accuracy_and_report_leave_one_out_errors():
    answerable, unanswerable = [0.5, 0.7, 0.9], [0.6, 0.4]
    proposal = propose(answerable, unanswerable)
    assert proposal["min_top_score"] == pytest.approx(0.65) and not proposal["separable"]
    assert (proposal["answerable_passed"], proposal["unanswerable_refused"]) == (2, 2)
    # Worked by hand: without 0.5, 0.7 or the 0.6 unanswerable, the new threshold misjudges the left-out question.
    assert leave_one_out_errors(answerable, unanswerable) == 3


def test_ties_take_the_wider_gap_and_empty_retrieval_counts_against_answerable():
    assert choose([0.6, 0.95], [0.5, 0.8]) == pytest.approx(0.875)
    proposal = propose([None, 0.9], [None, 0.5])
    assert proposal["min_top_score"] == pytest.approx(0.7) and (proposal["answerable_passed"], proposal["unanswerable_refused"]) == (1, 2)
    assert propose([0.9], []) is None and propose([], [0.1]) is None and propose([0.5], [0.5]) is None


# Configuration and binding (AC-18.5, Q-07)

def test_thresholds_load_from_configuration_and_are_validated(tmp_path, model_settings):
    scoring = scoring_config_id("bm25", model_settings, None)
    section = (f"[retrieval.sufficiency.bm25]\nmin_top_score = 0.3\nmin_chunk_score = 0.25\nmin_supporting_chunks = 2\n"
               f'calibration_run_id = "eval_abc"\nscoring_config_id = "{scoring}"\n')
    path = tmp_path / "config.toml"
    path.write_text(section, encoding="utf-8")
    loaded = load_settings(path).retrieval.sufficiency
    assert loaded.vector is None and loaded.bm25.model_dump() == {
        "min_top_score": 0.3, "min_chunk_score": 0.25, "min_supporting_chunks": 2, "calibration_run_id": "eval_abc", "scoring_config_id": scoring}
    for bad in (section.replace(scoring, "sc_short"), section.replace("= 2", "= 6"), section.replace("0.3", "1.3"),
                section.replace("bm25]", "hybrid]")):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            load_settings(path)


def test_active_thresholds_change_the_retrieval_config_id(indexed, qa_settings, registry, chat):
    before = ask(qa_settings, registry)
    calibrate(qa_settings, "bm25", 0.0)
    after = ask(qa_settings, registry)
    assert after.retrieval_config_id != before.retrieval_config_id
    assert search(SearchRequest(query=QUESTION, mode="bm25", top_k=5), qa_settings, registry).retrieval_config_id == after.retrieval_config_id
    calibrate(qa_settings, "bm25", 0.0, run_id="eval_other")
    assert ask(qa_settings, registry).retrieval_config_id not in (before.retrieval_config_id, after.retrieval_config_id)


def test_one_modes_thresholds_never_apply_to_another(indexed, qa_settings, registry, chat):
    calibrate(qa_settings, "vector", 1.0)
    response = ask(qa_settings, registry, mode="bm25")
    assert response.status == "answered" and codes(response) == {"SUFFICIENCY_NOT_CALIBRATED"}
    assert not response.sufficiency.calibrated and response.sufficiency.passed is None
    assert response.sufficiency.min_top_score is None and response.sufficiency.relevance_policy == "bm25-query-max-v1"
    assert ask(qa_settings, registry, mode="vector").reason == "LOW_RELEVANCE"


def test_thresholds_from_another_score_scale_are_stale_and_not_applied(indexed, qa_settings, registry, chat):
    uncalibrated = ask(qa_settings, registry, mode="vector").retrieval_config_id
    # Calibrated with another embedding model: a threshold of 1.0 would refuse everything, so answering shows it was not applied.
    other = qa_settings.model.model_copy(update={"embedding_model_digest": "b" * 64})
    calibrate(qa_settings, "vector", 1.0, scoring=scoring_config_id("vector", qa_settings, embedding_profile(other)))
    response = ask(qa_settings, registry, mode="vector")
    assert response.status == "answered" and codes(response) == {"SUFFICIENCY_CALIBRATION_STALE"}
    assert not response.sufficiency.calibrated and response.retrieval_config_id == uncalibrated
    # A changed BM25 parameter moves that scale too.
    calibrate(qa_settings, "bm25", 1.0)
    assert ask(qa_settings, registry, mode="bm25").reason == "LOW_RELEVANCE"
    qa_settings.retrieval.bm25_k1 = 1.5
    response = ask(qa_settings, registry, mode="bm25")
    assert response.status == "answered" and codes(response) == {"SUFFICIENCY_CALIBRATION_STALE"}


# The gate (FR-18.1, FR-18.2, AC-18.1)

def test_below_threshold_is_no_evidence_without_a_model_call(indexed, qa_settings, registry, chat):
    top = top_relevance(qa_settings, registry)
    calibrate(qa_settings, "bm25", top + 0.01, run_id="eval_gate")
    response = ask(qa_settings, registry)
    assert (response.status, response.reason, response.answer) == ("no_evidence", "LOW_RELEVANCE", generation.MESSAGES["LOW_RELEVANCE"])
    assert chat.prompts == [] and not response.llm_called and response.usage is None
    assert response.evidence == [] and response.chunks_used == 0 and response.chunks_retrieved > 0
    gate = response.sufficiency
    assert gate.calibrated and gate.passed is False and gate.top_score == round(top, 6)
    assert (gate.min_top_score, gate.calibration_run_id) == (pytest.approx(top + 0.01), "eval_gate")
    assert codes(response) == set()
    (entry,) = log_lines(qa_settings)
    assert entry["llm_called"] is False and entry["sufficiency"]["passed"] is False and entry["reason"] == "LOW_RELEVANCE"


def test_meeting_the_threshold_answers_and_shows_the_active_thresholds(indexed, qa_settings, registry, chat):
    top = top_relevance(qa_settings, registry)
    calibrate(qa_settings, "bm25", top, run_id="eval_gate")
    response = ask(qa_settings, registry)
    assert response.status == "answered" and response.llm_called and len(chat.prompts) == 1
    assert codes(response) == set() and response.sufficiency.passed and response.sufficiency.supporting_chunks >= 1
    assert response.sufficiency.calibration_run_id == "eval_gate" and response.sufficiency.min_top_score == top


def test_sufficiency_is_judged_after_trimming(indexed, qa_settings, registry, chat):
    from techdocqa.answering.generation import build_context
    question = "Kafka Redis HTTP templates guide"
    results = search(SearchRequest(query=question, mode="bm25", top_k=5), qa_settings, registry).results
    calibrate(qa_settings, "bm25", 0.0, chunk=0.0, supporting=2)
    full = ask(qa_settings, registry, question)
    assert full.status == "answered" and full.sufficiency.supporting_chunks == full.chunks_used == len(results) > 2
    # Only the top chunk fits, so every other supporting chunk is gone and cannot satisfy the gate.
    qa_settings.model.context_window = build_context(question, results[:1], qa_settings).token_bound + qa_settings.model.max_output_tokens
    response = ask(qa_settings, registry, question)
    assert (response.status, response.reason, response.sufficiency.supporting_chunks) == ("no_evidence", "LOW_RELEVANCE", 1)
    assert len(chat.prompts) == 1


# AC-18.3, AC-18.4: nothing retrieved and provider failures stay distinct from low relevance

def test_empty_index_and_filters_matching_nothing_are_no_matching_documents(qa_settings, registry, chat):
    for mode in ("bm25", "vector"):
        calibrate(qa_settings, mode, 0.5)
        response = ask(qa_settings, registry, mode=mode)
        assert (response.status, response.reason) == ("no_evidence", "NO_MATCHING_DOCUMENTS")
        assert response.sufficiency.calibrated and response.sufficiency.passed is None and response.sufficiency.top_score is None
    assert chat.prompts == []


def test_filter_matching_nothing_is_not_low_relevance(indexed, qa_settings, registry, chat):
    calibrate(qa_settings, "bm25", 0.0)
    response = ask(qa_settings, registry, technology="Nonexistent")
    assert (response.status, response.reason) == ("no_evidence", "NO_MATCHING_DOCUMENTS") and chat.prompts == []


def test_failing_model_with_good_retrieval_is_a_generation_error(indexed, qa_settings, registry, chat, embedder):
    calibrate(qa_settings, "bm25", 0.0)
    chat.replies = [ConnectionError("down")]
    response = ask(qa_settings, registry)
    assert (response.status, response.reason) == ("generation_error", "LLM_PROVIDER_UNAVAILABLE")
    assert response.sufficiency.passed and response.llm_called
    calibrate(qa_settings, "vector", 0.0)
    embedder.fail = True
    response = ask(qa_settings, registry, mode="vector")
    assert (response.status, response.reason) == ("generation_error", "EMBEDDING_PROVIDER_UNAVAILABLE") and not response.llm_called


# AC-21.1: a withdrawn document's answer is refused

def test_withdrawn_document_answer_is_refused(indexed, qa_settings, registry, chat):
    calibrate(qa_settings, "vector", top_relevance(qa_settings, registry, mode="vector"))
    assert ask(qa_settings, registry, mode="vector").status == "answered"
    withdraw_document(indexed["kafka.md"].document_id, "Licence withdrawn", registry)
    response = ask(qa_settings, registry, mode="vector")
    assert (response.status, response.reason) == ("no_evidence", "LOW_RELEVANCE") and response.chunks_retrieved > 0
    assert len(chat.prompts) == 1 and not response.llm_called


# CLI

def test_ask_text_explains_a_refusal_and_an_ungated_answer(indexed, qa_settings, registry, chat, tmp_path, capsys):
    config = Path(write_config(tmp_path, qa_settings))
    assert main(["ask", QUESTION, "--mode", "bm25", "--text", "--config", str(config)]) == 0
    assert "Warning: no calibrated relevance threshold applies" in capsys.readouterr().out
    loaded = load_settings(config)
    scoring = scoring_config_id("bm25", loaded, None)
    config.write_text(config.read_text(encoding="utf-8") + f"[retrieval.sufficiency.bm25]\nmin_top_score = 0.99\nmin_chunk_score = 0.99\n"
                      f'calibration_run_id = "eval_cli"\nscoring_config_id = "{scoring}"\n', encoding="utf-8")
    assert main(["ask", QUESTION, "--mode", "bm25", "--text", "--config", str(config)]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Status: no_evidence (LOW_RELEVANCE)") and "needs 0.99 (calibration run eval_cli)" in text
    # Only the first, ungated question reached the model.
    assert "Warning" not in text and len(chat.prompts) == 1
    assert main(["config-check", "--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["sufficiency"] == {"bm25": "calibrated", "vector": "not_calibrated"}


# Calibration in the eval report

def test_eval_proposes_thresholds_that_load_back_as_the_active_calibration(bench, qa_settings, registry, tmp_path):
    report = run_evaluation(bench["dataset"], bench["manifest"], qa_settings, registry, modes=["vector"])
    (row,) = report["configurations"]
    calibration = row["refusal_calibration"]
    assert calibration["active"] == {"status": "not_calibrated"} and calibration["relevance_policy"] == "cosine-distance-half-v1"
    proposed = calibration["proposed"]
    assert proposed["answerable"] == 3 and proposed["unanswerable"] == 1 and 0 < proposed["min_top_score"] < 1
    markdown = render_markdown(report)
    assert "## Refusal calibration (FR-18)" in markdown and f'calibration_run_id = "{report["run_id"]}"' in markdown
    # The proposed section, pasted into a configuration, is what the next run and every answer use.
    block = markdown.split("```toml\n", 1)[1].split("\n```", 1)[0]
    config = Path(write_config(tmp_path, qa_settings))
    config.write_text(config.read_text(encoding="utf-8") + block + "\n", encoding="utf-8")
    loaded = load_settings(config)
    assert loaded.retrieval.sufficiency.vector.calibration_run_id == report["run_id"]
    qa_settings.retrieval.sufficiency = loaded.retrieval.sufficiency
    first, second = (run_evaluation(bench["dataset"], bench["manifest"], qa_settings, registry, modes=["vector"]) for _ in range(2))
    active = first["configurations"][0]["refusal_calibration"]["active"]
    assert active["status"] == "calibrated" and active["calibration_run_id"] == report["run_id"]
    assert (active["answerable_passed"], active["unanswerable_refused"]) == (proposed["answerable_passed"], proposed["unanswerable_refused"])
    assert first["results_fingerprint"] == second["results_fingerprint"] != report["results_fingerprint"]
    assert first["configurations"][0]["retrieval_config_id"] != row["retrieval_config_id"]


# The refusal run (AC-18.1, AC-18.2)

@pytest.fixture
def no_warm_up(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "warm_up", lambda settings: calls.append(1) or {"loaded": True, "ms": 1, "code": None})
    return calls


def bench_threshold(bench, settings, registry):
    """Between the unanswerable question's top relevance and the weakest answerable one, asserted to exist."""
    from techdocqa.evaluation.dataset import load_dataset
    tops = {question.id: (question.unanswerable, top_relevance(settings, registry, question.question, "vector"))
            for question in load_dataset(bench["dataset"]).questions}
    weakest = min(score for unanswerable, score in tops.values() if not unanswerable)
    strongest = max(score for unanswerable, score in tops.values() if unanswerable)
    assert strongest < weakest
    return (weakest + strongest) / 2


def test_refusal_run_reports_both_criteria_and_no_calls_for_gate_refusals(bench, qa_settings, registry, chat, no_warm_up):
    from techdocqa.evaluation.answers import render_refusal_markdown, run_refusal_check
    calibrate(qa_settings, "vector", bench_threshold(bench, qa_settings, registry), run_id="eval_bench")
    report = run_refusal_check(bench["dataset"], bench["manifest"], qa_settings, registry, mode="vector")
    summary = report["summary"]
    assert no_warm_up == [1] and report["environment"]["warm_up"]["loaded"]
    assert summary["ac_18_1"] == {"questions": 1, "no_evidence": 1, "rate": 1.0, "target": 0.9, "reasons": {"LOW_RELEVANCE": 1},
                                  "met": False}
    assert summary["ac_18_2"] == {"questions": 3, "answered": 3, "rate": 1.0, "target": 0.85, "reasons": {"answered": 3}, "met": False}
    assert (summary["gate_refusals"], summary["llm_calls_on_gate_refusals"], summary["llm_calls"]) == (1, 0, 3)
    assert len(chat.prompts) == 3 and report["retrieval"]["sufficiency"]["calibration_run_id"] == "eval_bench"
    markdown = render_refusal_markdown(report)
    assert "1 of 1 = 1.0, target 0.9 (NOT met)" in markdown and "| ood-1 | yes | no_evidence | LOW_RELEVANCE |" in markdown


def test_eval_refusal_cli_writes_reports_and_fails_on_generation_errors(bench, qa_settings, registry, chat, no_warm_up, tmp_path, capsys):
    config = write_config(tmp_path, qa_settings)
    reports = tmp_path / "reports"
    arguments = ["eval", "--refusal", "--mode", "vector", "--dataset", str(bench["dataset"]), "--manifest", str(bench["manifest"]),
                 "--report-dir", str(reports), "--config", config]
    assert main(arguments) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"].startswith("refusal_") and "questions" not in payload
    saved = json.loads(Path(payload["report_files"]["json"]).read_text(encoding="utf-8"))
    assert len(saved["questions"]) == 4 and Path(payload["report_files"]["markdown"]).parent == reports
    chat.replies = [ConnectionError("down")]
    assert main(arguments) == 1
    capsys.readouterr()
    for bad in (["eval", "--refusal", "--answers", "2"], ["eval", "--refusal", "--mode", "bm25", "--mode", "vector"]):
        assert main([*bad, "--config", config]) == 2
        assert json.loads(capsys.readouterr().err)["error"]["code"] == "INVALID_ARGUMENT"


# Warm-up before timed runs

def test_warm_up_preloads_the_model_with_the_answering_window(qa_settings, monkeypatch):
    import ollama
    sent = []
    monkeypatch.setattr(ollama.Client, "generate", lambda self, **kwargs: sent.append(kwargs))
    assert generation.warm_up(qa_settings)["loaded"]
    assert sent == [{"model": "scripted", "prompt": "", "options": {"num_ctx": qa_settings.model.context_window}}]
    def down(self, **kwargs):
        raise ConnectionError("Failed to connect to a secret host")
    monkeypatch.setattr(ollama.Client, "generate", down)
    assert generation.warm_up(qa_settings) == {"loaded": False, "ms": pytest.approx(0, abs=1000), "code": "LLM_PROVIDER_UNAVAILABLE"}
    qa_settings.model.provider = "openai"
    assert generation.warm_up(qa_settings) == {"loaded": False, "ms": 0, "code": None}


def test_hybrid_has_no_thresholds_to_borrow(qa_settings):
    calibrate(qa_settings, "bm25", 0.5)
    calibrate(qa_settings, "vector", 0.5)
    assert sufficiency.active_thresholds("hybrid", qa_settings, None) == (None, sufficiency.NOT_CALIBRATED)
