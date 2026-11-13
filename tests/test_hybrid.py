"""FR-14 hybrid search (AC-14.1 to AC-14.4) and its FR-18 gate (P10-1 to P10-3), offline with the counting fake embedder."""

import tomllib

import pytest

from techdocqa.answering import sufficiency
from techdocqa.errors import TechDocQAError
from techdocqa.evaluation.runner import render_markdown, run_evaluation
from techdocqa.indexing import embeddings
from techdocqa.retrieval import search as search_module
from techdocqa.retrieval.lexical import LexicalIndex
from techdocqa.retrieval.search import retrieval_config_id, rrf, scoring_config_id, search, stored_relevances
from techdocqa.schemas import SearchFilters, SearchRequest, SearchResult
from techdocqa.settings import HybridThresholds, SufficiencyLevels, SufficiencyThresholds
# Shared fixtures: inline workers, the counting embedder, a verified profile, an indexed corpus, a scripted chat model.
from test_evaluation import bench  # noqa: F401
from test_generation import chat, qa_settings  # noqa: F401
from test_indexing import collection, embedder, indexed, inline_workers, model_settings  # noqa: F401

KAFKA = "How do Kafka brokers replicate partitions?"


def query(settings, registry, text=KAFKA, mode="hybrid", top_k=5, **filters):
    return search(SearchRequest(query=text, mode=mode, top_k=top_k, filters=SearchFilters(**filters)), settings, registry)


def levels(value):
    return SufficiencyLevels(min_top_score=value, min_chunk_score=value, min_supporting_chunks=1)


def hybrid_gate(settings, gate, bm25=None, vector=None):
    profile = embeddings.embedding_profile(settings.model)
    return HybridThresholds(gate=gate, bm25=levels(bm25) if bm25 is not None else None,
                            vector=levels(vector) if vector is not None else None, calibration_run_id="eval_test",
                            scoring_config_id=scoring_config_id("hybrid", settings, profile))


# Fusion (AC-14.2, P10-1)

def test_rrf_matches_a_hand_computed_example_to_four_decimals():
    # a: 1/(60+1) + 1/(60+2) = 0.016393 + 0.016129 = 0.032522. c: 1/(60+3) + 1/(60+1) = 0.015873 + 0.016393 = 0.032266.
    # b: 1/(60+2) = 0.016129.
    fused = rrf({"bm25": ["a", "b", "c"], "vector": ["c", "a"]}, 60, {"bm25": 1.0, "vector": 1.0})
    assert [(chunk, round(score, 4)) for chunk, score in fused] == [("a", 0.0325), ("c", 0.0323), ("b", 0.0161)]
    # Weight 2 on BM25: a 2/61 + 1/62 = 0.048916, c 2/63 + 1/61 = 0.048139, b 2/62 = 0.032258.
    weighted = rrf({"bm25": ["a", "b", "c"], "vector": ["c", "a"]}, 60, {"bm25": 2.0, "vector": 1.0})
    assert [(chunk, round(score, 4)) for chunk, score in weighted] == [("a", 0.0489), ("c", 0.0481), ("b", 0.0323)]
    # Equal scores go to chunk_id, so the order never depends on which retriever answered first.
    assert [chunk for chunk, _ in rrf({"vector": ["y"], "bm25": ["x"]}, 60, {"bm25": 1.0, "vector": 1.0})] == ["x", "y"]


def test_a_chunk_found_by_both_retrievers_appears_once_with_both_ranks(indexed, model_settings, registry):
    response = query(model_settings, registry)
    ids = [result.chunk_id for result in response.results]
    assert response.mode == "hybrid" and not response.degraded and len(ids) == len(set(ids)) == 5
    top = response.results[0]
    assert set(top.ranks) == {"bm25", "vector", "hybrid"} and top.ranks["hybrid"] == top.rank == 1
    bm25 = {result.chunk_id: result for result in query(model_settings, registry, mode="bm25", top_k=20).results}
    vector = {result.chunk_id: result for result in query(model_settings, registry, mode="vector", top_k=20).results}
    # The fused score is rrf-v1 over the ranks each retriever gave, and each component keeps its raw score.
    assert top.scores["hybrid"] == pytest.approx(1 / (60 + top.ranks["bm25"]) + 1 / (60 + top.ranks["vector"]))
    assert top.ranks["bm25"] == bm25[top.chunk_id].rank and top.ranks["vector"] == vector[top.chunk_id].rank
    assert top.scores["bm25"] == bm25[top.chunk_id].scores["bm25"] and top.scores["vector"] == vector[top.chunk_id].scores["vector"]


def test_one_query_three_modes_one_interface(indexed, model_settings, registry):
    for mode in ("bm25", "vector", "hybrid"):
        response = query(model_settings, registry, mode=mode)
        assert response.mode == mode and response.results and response.retrieval_config_id.startswith("rc_")
        assert all(result.rank == index for index, result in enumerate(response.results, 1))


# Component relevances (P10-3)

def test_every_fused_chunk_carries_both_component_relevances(indexed, model_settings, registry):
    response = query(model_settings, registry)
    bm25 = {result.chunk_id: result.relevance for result in query(model_settings, registry, mode="bm25", top_k=20).results}
    vector = {result.chunk_id: result.relevance for result in query(model_settings, registry, mode="vector", top_k=20).results}
    # Only the Kafka chunks share a word with the question, so the rest are ranked by the vector retriever alone.
    assert any("bm25" not in result.ranks for result in response.results)
    for result in response.results:
        assert result.relevance is None and set(result.relevances) == {"bm25", "vector"}
        # A chunk BM25 did not rank shares no query word, so its BM25 relevance is 0 on the same scale.
        assert result.relevances["bm25"] == pytest.approx(bm25.get(result.chunk_id, 0.0))
        assert result.relevances["vector"] == pytest.approx(vector[result.chunk_id], abs=1e-6)


def test_stored_vectors_give_the_vector_relevance_chroma_gives(indexed, model_settings, registry):
    profile = embeddings.embedding_profile(model_settings.model)
    ranked = query(model_settings, registry, mode="vector", top_k=20).results
    current = {record.version_id: record for record in registry.eligible_versions() if record.status == "indexed"}
    vector = embeddings.embed_query(KAFKA, model_settings, profile)
    computed = stored_relevances(collection(model_settings), vector, current, {result.chunk_id for result in ranked})
    assert set(computed) == {result.chunk_id for result in ranked}
    for result in ranked:
        assert computed[result.chunk_id] == pytest.approx(result.scores["vector"], abs=1e-6)


def test_a_chunk_only_bm25_ranked_gets_its_vector_relevance_from_the_stored_vector(indexed, model_settings, registry, monkeypatch):
    vector = {result.chunk_id: result.scores["vector"] for result in query(model_settings, registry, mode="vector", top_k=20).results}
    real = search_module.vector_search
    def first_only(*args, **kwargs):
        live, *rest = real(*args, **kwargs)
        return live[:1], *rest
    monkeypatch.setattr(search_module, "vector_search", first_only)
    response = query(model_settings, registry)
    looked_up = [result for result in response.results if "vector" not in result.ranks]
    assert looked_up
    for result in looked_up:
        assert result.relevances["vector"] == pytest.approx(vector[result.chunk_id], abs=1e-6)
        assert result.scores["vector"] == result.relevances["vector"]


# Degraded hybrid (AC-14.3, P10-2)

def test_vector_failing_returns_bm25_results_marked_degraded(indexed, model_settings, registry, embedder):
    bm25 = query(model_settings, registry, mode="bm25")
    embedder.fail = True
    response = query(model_settings, registry)
    assert response.degraded and response.degradation_reason == "EMBEDDING_PROVIDER_UNAVAILABLE" and response.failed_retriever == "vector"
    assert [result.chunk_id for result in response.results] == [result.chunk_id for result in bm25.results]
    for degraded, alone in zip(response.results, bm25.results, strict=True):
        assert degraded.relevance == alone.relevance and degraded.relevances == {"bm25": alone.relevance, "vector": None}
        assert set(degraded.ranks) == {"bm25", "hybrid"}
    assert "secret provider detail" not in response.model_dump_json()


def test_bm25_failing_returns_vector_results_marked_degraded(indexed, model_settings, registry, monkeypatch):
    vector = query(model_settings, registry, mode="vector")
    def broken(*args, **kwargs):
        raise TechDocQAError("CHUNK_ARTIFACT_INVALID", "A stored chunk artifact failed validation.", stage="search")
    monkeypatch.setattr(search_module, "bm25_ranked", broken)
    response = query(model_settings, registry)
    assert response.degraded and (response.failed_retriever, response.degradation_reason) == ("bm25", "CHUNK_ARTIFACT_INVALID")
    assert [result.chunk_id for result in response.results] == [result.chunk_id for result in vector.results]
    assert [result.relevance for result in response.results] == [result.relevance for result in vector.results]


def test_both_failing_is_a_search_error_and_configuration_errors_are_not_degradation(indexed, model_settings, registry, embedder,
                                                                                      monkeypatch):
    def broken(stage):
        def fail(*args, **kwargs):
            raise TechDocQAError("CHUNK_ARTIFACT_INVALID", "A stored chunk artifact failed validation.", stage=stage)
        return fail
    monkeypatch.setattr(search_module, "bm25_ranked", broken("search"))
    embedder.fail = True
    with pytest.raises(TechDocQAError) as caught:
        query(model_settings, registry)
    error = caught.value.response.error
    assert error.code == "HYBRID_SEARCH_FAILED" and error.retryable
    assert "bm25 CHUNK_ARTIFACT_INVALID" in error.message and "vector EMBEDDING_PROVIDER_UNAVAILABLE" in error.message
    embedder.fail = False
    monkeypatch.setattr(search_module, "bm25_ranked", broken("configuration"))
    with pytest.raises(TechDocQAError) as caught:
        query(model_settings, registry)
    assert caught.value.response.error.code == "CHUNK_ARTIFACT_INVALID"


# Invariant 1: the P0 modes do not move

def test_bm25_mode_still_fetches_top_k_and_hybrid_fetches_the_candidate_depth(indexed, model_settings, registry, monkeypatch):
    depths = []
    real = LexicalIndex.search
    monkeypatch.setattr(LexicalIndex, "search", lambda self, text, top_k, allowed=lambda chunk: True:
                        depths.append(top_k) or real(self, text, top_k, allowed))
    model_settings.retrieval.candidate_depth = 3
    query(model_settings, registry, mode="bm25", top_k=7)
    query(model_settings, registry, mode="bm25", top_k=2)
    query(model_settings, registry, top_k=7)
    query(model_settings, registry, top_k=2)
    assert depths == [7, 2, 7, 3]


def test_fusion_settings_move_only_the_hybrid_ids(indexed, model_settings, registry):
    profile = embeddings.embedding_profile(model_settings.model)
    def ids():
        found = {}
        for mode in ("bm25", "vector", "hybrid"):
            scale = None if mode == "bm25" else profile
            found[mode] = scoring_config_id(mode, model_settings, scale), retrieval_config_id(SearchRequest(query="x", mode=mode), model_settings, scale)
        return found
    before = ids()
    for field, value in (("rrf_k", 30), ("rrf_bm25_weight", 2.0), ("rrf_vector_weight", 0.5)):
        original = getattr(model_settings.retrieval, field)
        setattr(model_settings.retrieval, field, value)
        after = ids()
        assert after["bm25"] == before["bm25"] and after["vector"] == before["vector"]
        assert after["hybrid"][0] != before["hybrid"][0] and after["hybrid"][1] != before["hybrid"][1]
        setattr(model_settings.retrieval, field, original)
    assert ids() == before
    # A degraded hybrid search is judged by the surviving mode's thresholds, so they are part of hybrid's configuration.
    model_settings.retrieval.sufficiency.bm25 = SufficiencyThresholds(
        min_top_score=0.2, min_chunk_score=0.2, calibration_run_id="eval_test", scoring_config_id=scoring_config_id("bm25", model_settings, None))
    assert ids()["hybrid"][1] != before["hybrid"][1] and ids()["hybrid"][0] == before["hybrid"][0]


# The hybrid gate (P10-3)

def test_hybrid_thresholds_need_the_components_their_gate_judges(model_settings):
    with pytest.raises(ValueError, match="needs thresholds for vector"):
        HybridThresholds(gate="either", bm25=levels(0.3), calibration_run_id="eval_test", scoring_config_id="sc_" + "0" * 64)
    gate = HybridThresholds(gate="bm25", bm25=levels(0.3), vector=levels(0.8), calibration_run_id="eval_test", scoring_config_id="sc_" + "0" * 64)
    assert list(gate.components()) == ["bm25"]


def test_each_gate_judges_its_components(model_settings):
    values = {"bm25": [0.5, 0.1], "vector": [0.84]}
    def verdict(gate, bm25=0.3, vector=0.85):
        return sufficiency.judge_gate(values, HybridThresholds(gate=gate, bm25=levels(bm25), vector=levels(vector),
                                                               calibration_run_id="eval_test", scoring_config_id="sc_" + "0" * 64))
    checks, passed = verdict("bm25")
    assert passed and checks == {"bm25": (1, True)}
    assert verdict("vector")[1] is False
    assert verdict("either")[1] is True and verdict("both")[1] is False
    assert verdict("both", vector=0.8)[1] is True
    # A component with no relevance at all, such as an unindexed chunk's vector, fails that component.
    assert sufficiency.judge_gate({"bm25": [0.5]}, HybridThresholds(gate="both", bm25=levels(0.3), vector=levels(0.5),
                                  calibration_run_id="eval_test", scoring_config_id="sc_" + "0" * 64))[1] is False


def test_hybrid_proposals_match_a_hand_computed_example():
    answerable = [{"bm25": 0.5, "vector": 0.9}, {"bm25": 0.4, "vector": 0.88}]
    unanswerable = [{"bm25": 0.1, "vector": 0.8}, {"bm25": 0.2, "vector": 0.85}]
    proposal = sufficiency.propose_hybrid(answerable, unanswerable)
    by_gate = {candidate["gate"]: candidate for candidate in proposal["candidates"]}
    # Vector: midpoints 0.825, 0.865 and 0.89 score 1.5, 2 and 1.5 in balanced accuracy, so 0.865; its margin is
    # |0.85 - 0.865| = |0.88 - 0.865| = 0.015. Leaving out the 0.85 negative moves the threshold to 0.84, which it passes.
    assert (by_gate["vector"]["thresholds"], by_gate["vector"]["margin"], by_gate["vector"]["leave_one_out_errors"]) == (
        {"vector": 0.865}, 0.015, 1)
    # BM25: midpoint 0.3 between 0.2 and 0.4, margin 0.1, no leave-one-out error.
    assert (by_gate["bm25"]["thresholds"], by_gate["bm25"]["margin"], by_gate["bm25"]["leave_one_out_errors"]) == ({"bm25": 0.3}, 0.1, 0)
    # Either and both reuse those thresholds. Either's closest question is the 0.85 negative: max(-0.1, -0.015).
    assert by_gate["either"]["thresholds"] == by_gate["both"]["thresholds"] == {"bm25": 0.3, "vector": 0.865}
    assert (by_gate["either"]["margin"], by_gate["either"]["leave_one_out_errors"]) == (0.015, 1)
    assert (by_gate["both"]["margin"], by_gate["both"]["leave_one_out_errors"]) == (0.015, 0)
    assert all(candidate["separable"] for candidate in proposal["candidates"])
    # Fewest leave-one-out errors (bm25 and both, 0), then the larger margin: bm25.
    assert proposal["gate"] == "bm25" and proposal["thresholds"] == {"bm25": 0.3}


def test_a_full_tie_goes_to_the_vector_gate_and_missing_components_fail_both():
    same = [{"bm25": 0.9, "vector": 0.9}, {"bm25": 0.8, "vector": 0.8}], [{"bm25": 0.2, "vector": 0.2}, {"bm25": 0.1, "vector": 0.1}]
    assert sufficiency.propose_hybrid(*same)["gate"] == "vector"
    assert sufficiency.gate_passes("both", {"bm25": 0.9, "vector": None}, {"bm25": 0.3, "vector": 0.5}) is False
    assert sufficiency.gate_passes("either", {"bm25": 0.9, "vector": None}, {"bm25": 0.3, "vector": 0.5}) is True
    assert sufficiency.gate_distance("both", {"bm25": 0.9, "vector": None}, {"bm25": 0.3, "vector": 0.5}) is None
    assert sufficiency.propose_hybrid([], [{"bm25": 0.1, "vector": 0.1}]) is None


def test_the_proposed_section_loads_as_configuration(settings):
    proposal = sufficiency.propose_hybrid([{"bm25": 0.5, "vector": 0.9}, {"bm25": 0.4, "vector": 0.88}],
                                          [{"bm25": 0.1, "vector": 0.8}, {"bm25": 0.2, "vector": 0.85}])
    proposal = {**proposal, "gate": "both", "thresholds": {"bm25": 0.3, "vector": 0.865}}
    section = tomllib.loads(sufficiency.hybrid_toml_block(proposal, "eval_test", "sc_" + "1" * 64))["retrieval"]["sufficiency"]["hybrid"]
    loaded = HybridThresholds(**section)
    assert loaded.gate == "both" and loaded.bm25.min_top_score == 0.3 and loaded.vector.min_chunk_score == 0.865


def test_record_judges_the_kept_chunks_on_their_component_relevances(model_settings):
    kept = [SearchResult(rank=1, chunk_id="c1", document_id="d", version_id="v", text="t", scores={}, ranks={},
                         relevances={"bm25": 0.45, "vector": 0.86}),
            SearchResult(rank=2, chunk_id="c2", document_id="d", version_id="v", text="t", scores={}, ranks={},
                         relevances={"bm25": 0.1, "vector": None})]
    gate = HybridThresholds(gate="both", bm25=levels(0.3), vector=levels(0.9), calibration_run_id="eval_test", scoring_config_id="sc_" + "0" * 64)
    check = sufficiency.record(sufficiency.new_check("hybrid", gate), kept, gate)
    assert check.gate == "both" and check.passed is False and check.top_score is None
    assert check.components["bm25"].passed and check.components["bm25"].top_score == 0.45 and check.components["bm25"].supporting_chunks == 1
    assert check.components["vector"].passed is False and check.components["vector"].top_score == 0.86


def test_hybrid_thresholds_go_stale_when_the_fusion_changes(model_settings):
    profile = embeddings.embedding_profile(model_settings.model)
    model_settings.retrieval.sufficiency.hybrid = hybrid_gate(model_settings, "vector", vector=0.5)
    assert sufficiency.active_thresholds("hybrid", model_settings, profile)[0] is not None
    model_settings.retrieval.rrf_k = 30
    assert sufficiency.active_thresholds("hybrid", model_settings, profile) == (None, sufficiency.STALE)


# Answers in hybrid mode

def test_ask_in_hybrid_mode_is_gated_on_component_relevances(indexed, qa_settings, registry, chat):
    qa_settings.retrieval.sufficiency.hybrid = hybrid_gate(qa_settings, "both", bm25=0.99, vector=0.99)
    from techdocqa.answering.generation import answer_question
    refused = answer_question(KAFKA, qa_settings, registry, mode="hybrid")
    assert (refused.status, refused.reason, refused.mode, refused.llm_called) == ("no_evidence", "LOW_RELEVANCE", "hybrid", False)
    assert refused.sufficiency.gate == "both" and set(refused.sufficiency.components) == {"bm25", "vector"} and chat.prompts == []
    qa_settings.retrieval.sufficiency.hybrid = hybrid_gate(qa_settings, "either", bm25=0.01, vector=0.01)
    answered = answer_question(KAFKA, qa_settings, registry, mode="hybrid")
    assert answered.status == "answered" and answered.sufficiency.passed and not answered.degraded
    assert not {warning.code for warning in answered.warnings} & {sufficiency.NOT_CALIBRATED, sufficiency.STALE}


def test_degraded_ask_uses_the_surviving_modes_thresholds(indexed, qa_settings, registry, chat, embedder):
    from techdocqa.answering.generation import answer_question
    qa_settings.retrieval.sufficiency.hybrid = hybrid_gate(qa_settings, "vector", vector=0.01)
    qa_settings.retrieval.sufficiency.bm25 = SufficiencyThresholds(
        min_top_score=0.99, min_chunk_score=0.99, calibration_run_id="eval_test", scoring_config_id=scoring_config_id("bm25", qa_settings, None))
    embedder.fail = True
    response = answer_question(KAFKA, qa_settings, registry, mode="hybrid")
    assert response.degraded and response.degradation_reason == "EMBEDDING_PROVIDER_UNAVAILABLE"
    assert (response.status, response.reason) == ("no_evidence", "LOW_RELEVANCE") and chat.prompts == []
    assert response.sufficiency.thresholds_from == "bm25" and response.sufficiency.min_top_score == 0.99
    assert "SEARCH_DEGRADED" in {warning.code for warning in response.warnings}
    qa_settings.retrieval.sufficiency.bm25 = None
    ungated = answer_question(KAFKA, qa_settings, registry, mode="hybrid")
    assert ungated.status == "answered" and {"SEARCH_DEGRADED", sufficiency.NOT_CALIBRATED} <= {warning.code for warning in ungated.warnings}


def test_degraded_ask_with_nothing_found_is_a_provider_failure(indexed, qa_settings, registry, chat, embedder):
    from techdocqa.answering.generation import answer_question
    embedder.fail = True
    response = answer_question("How do Terraform workspaces work?", qa_settings, registry, mode="hybrid")
    assert (response.status, response.reason, response.retryable) == ("generation_error", "EMBEDDING_PROVIDER_UNAVAILABLE", True)
    assert response.degraded and chat.prompts == []


# Evaluation in hybrid mode

def test_hybrid_evaluation_keeps_component_relevances_and_proposes_a_gate(bench, model_settings, registry):
    report = run_evaluation(bench["dataset"], bench["manifest"], model_settings, registry, modes=["hybrid"])
    [row] = report["configurations"]
    assert row["status"] == "completed" and row["metrics"]["ndcg@5"] is not None
    question = next(item for item in report["questions"] if item["id"] == "kafka-1")["results"]["hybrid"]
    assert set(question["relevances"]) == {"bm25", "vector"} and len(question["relevances"]["vector"]) == len(question["ranked"])
    calibration = row["refusal_calibration"]
    assert calibration["gate_selection"] == sufficiency.HYBRID_SELECTION_POLICY and calibration["active"]["status"] == "not_calibrated"
    assert calibration["proposed"]["gate"] in sufficiency.GATES and len(calibration["proposed"]["candidates"]) == 4
    markdown = render_markdown(report)
    assert "### hybrid: gate candidates (P10-3)" in markdown and "[retrieval.sufficiency.hybrid]" in markdown


def test_a_degraded_search_fails_the_hybrid_configuration(bench, model_settings, registry, embedder):
    embedder.fail = True
    report = run_evaluation(bench["dataset"], bench["manifest"], model_settings, registry, modes=["bm25", "hybrid"])
    bm25, hybrid = report["configurations"]
    assert bm25["status"] == "completed"
    assert hybrid["status"] == "failed" and hybrid["error"]["code"] == "SEARCH_DEGRADED"
    assert "4 of 4 searches were degraded: vector EMBEDDING_PROVIDER_UNAVAILABLE 4" in hybrid["error"]["message"]
