"""FR-17 citation verification, offline with the scripted chat model and the indexed fixture corpus."""

import random

import pytest

from techdocqa.answering.citations import cited_labels, remove_labels
from techdocqa.indexing.lifecycle import withdraw_document
from techdocqa.ingestion.chunks import stored_chunks
# Shared fixtures: the indexed Phase 5 corpus and the scripted chat model with a verified chat profile.
from test_generation import all_chunks, ask, chat, log_lines, qa_settings  # noqa: F401
from test_indexing import embedder, indexed, inline_workers, model_settings  # noqa: F401

QUESTION = "Kafka Redis HTTP templates guide"


@pytest.mark.parametrize("answer, labels", [
    ("Brokers replicate [C1]. Keys expire [C3][C1].", ["C1", "C3"]),
    ("Both apply [C2, C4; C2].", ["C2", "C4"]),
    ("No citation here, only arr[i] and [Ctrl] and C1.", []),
    ("Spaces are allowed [ C5 ].", ["C5"]),
])
def test_labels_are_read_in_order_of_first_appearance(answer, labels):
    assert cited_labels(answer) == labels


@pytest.mark.parametrize("answer, removed, expected", [
    ("Brokers replicate [C1] and [C9].", {"C9"}, "Brokers replicate [C1] and."),
    ("Both apply [C1, C9].", {"C9"}, "Both apply [C1]."),
    ("Only [C9] here [C9].", {"C9"}, "Only here."),
    ("Untouched [C1,C2].", {"C9"}, "Untouched [C1,C2]."),
])
def test_removed_labels_leave_no_marker_or_gap(answer, removed, expected):
    assert remove_labels(answer, removed) == expected


# AC-17.1

def test_unknown_label_is_removed_and_logged_once(indexed, qa_settings, registry, chat):
    chat.replies = ["Kafka brokers replicate partitions [C1]. Redis evicts keys [C9]."]
    response = ask(qa_settings, registry, QUESTION, mode="vector")
    assert response.chunks_used == 5 and response.status == "answered"
    assert [citation.label for citation in response.citations] == ["C1"]
    assert response.answer == "Kafka brokers replicate partitions [C1]. Redis evicts keys."
    removed = [warning for warning in response.warnings if warning.code == "INVALID_CITATION_REMOVED"]
    assert [warning.label for warning in removed] == ["C9"]
    (entry,) = log_lines(qa_settings)
    assert [warning for warning in entry["warnings"] if warning["code"] == "INVALID_CITATION_REMOVED"] == [
        {"code": "INVALID_CITATION_REMOVED", "label": "C9"}]


# AC-17.2

def test_every_citation_in_thirty_responses_resolves_to_an_active_chunk(indexed, qa_settings, registry, chat):
    rng = random.Random(7)
    questions = ["How do Kafka brokers replicate partitions?", "How does Redis evict keys?", "What does HTTP/2 negotiate?",
                 "How do C++ templates generate code?", QUESTION]
    def reply(messages):
        labels = rng.sample(["C1", "C2", "C3", "C4", "C5", "C7", "C12"], k=rng.randint(1, 4))
        return "The sources say so " + "".join(f"[{label}]" for label in labels) + "."
    chat.replies = [reply]
    checked = 0
    for index in range(30):
        response = ask(qa_settings, registry, questions[index % len(questions)], mode=("bm25", "vector")[index % 2])
        eligible = {record.version_id: record for record in registry.eligible_versions()}
        for citation in response.citations + response.context_consulted:
            record = eligible[citation.version_id]
            chunk = {chunk["chunk_id"]: chunk for chunk in stored_chunks(record, qa_settings)}[citation.chunk_id]
            assert (chunk["document_id"], record.document_id) == (citation.document_id, citation.document_id)
            assert citation.chunk_id in response.evidence
            checked += 1
        assert all(f"[{warning.label}]" not in (response.answer or "") for warning in response.warnings if warning.label)
    assert checked >= 30


# AC-17.3

def test_no_citation_is_no_evidence_when_strict(indexed, qa_settings, registry, chat):
    chat.replies = ["Kafka brokers replicate partitions across the cluster."]
    response = ask(qa_settings, registry)
    assert (response.status, response.reason, response.citation_verified) == ("no_evidence", "NO_VALID_CITATIONS", False)
    assert response.citations == [] and response.sources == [] and response.evidence
    assert "replicate" not in response.answer


def test_no_citation_is_unverified_context_when_not_strict(indexed, qa_settings, registry, chat):
    qa_settings.answering.strict_citations = False
    chat.replies = ["Kafka brokers replicate partitions across the cluster."]
    response = ask(qa_settings, registry, QUESTION, mode="vector")
    assert (response.status, response.citation_verified) == ("answered", False)
    assert response.answer == "Kafka brokers replicate partitions across the cluster."
    assert response.citations == []
    assert [citation.chunk_id for citation in response.context_consulted] == response.evidence
    assert [citation.label for citation in response.context_consulted] == [f"C{index}" for index in range(1, 6)]
    assert len({source.version_id for source in response.sources}) == len(response.sources)
    assert {source.version_id for source in response.sources} == {citation.version_id for citation in response.context_consulted}


def test_non_strict_mode_still_verifies_citations_it_can(indexed, qa_settings, registry, chat):
    qa_settings.answering.strict_citations = False
    response = ask(qa_settings, registry)
    assert (response.status, response.citation_verified) == ("answered", True)
    assert response.citations and response.context_consulted == []


def test_only_invalid_citations_leave_nothing_to_show(indexed, qa_settings, registry, chat):
    chat.replies = ["[C9]"]
    for strict in (True, False):
        qa_settings.answering.strict_citations = strict
        response = ask(qa_settings, registry)
        assert (response.status, response.reason) == ("no_evidence", "NO_VALID_CITATIONS")


# AC-17.4 and FR-17.3

def test_citations_use_stored_metadata_even_when_the_model_names_sources(indexed, qa_settings, registry, chat):
    chat.replies = ["See https://evil.example/kafka, titled 'Official Kafka Bible' [C1] [C2]."]
    response = ask(qa_settings, registry, QUESTION, mode="vector")
    chunks = all_chunks(qa_settings, registry)
    for citation in response.citations:
        record = registry.get_version(citation.version_id)
        chunk = chunks[citation.chunk_id]
        assert (citation.title, citation.source, citation.source_url) == (record.title, record.source_key, record.source_url)
        assert (citation.section_path, citation.page) == (" > ".join(chunk["section_path"]) or None, chunk["page"])
        assert "evil.example" not in citation.model_dump_json() and "Bible" not in citation.model_dump_json()
    assert [citation.label for citation in response.citations] == ["C1", "C2"]


def test_a_source_withdrawn_during_generation_is_not_cited(indexed, qa_settings, registry, chat):
    version = indexed["kafka.md"]
    def withdraw_then_answer(messages):
        withdraw_document(version.document_id, "Withdrawn while answering", registry)
        return "Kafka brokers replicate partitions [C1]."
    chat.replies = [withdraw_then_answer]
    response = ask(qa_settings, registry)
    assert (response.status, response.reason) == ("no_evidence", "NO_VALID_CITATIONS")
    assert [(warning.code, warning.label) for warning in response.warnings if warning.label] == [("CITATION_SOURCE_INACTIVE", "C1")]
