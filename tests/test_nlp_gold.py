"""The Phase 9 gold-data tool (P9-9): sentence marks, paragraph sampling, ambiguous-use stratum and label normalization."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nlp_gold", ROOT / "datasets" / "nlp_gold.py")
nlp_gold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nlp_gold)
MARK = nlp_gold.MARK


def test_marks_round_trip_and_exclude_surrounding_whitespace():
    text = "First one.\nSecond, wrapped\nover lines. Third."
    sentences = nlp_gold.draft(text)
    assert [text[a:b] for a, b in sentences] == ["First one.", "Second, wrapped\nover lines.", "Third."]
    plain, found = nlp_gold.unmarked(nlp_gold.marked(text, sentences))
    assert plain == text and found == [list(span) for span in sentences]


def test_a_moved_mark_changes_only_the_boundaries():
    text = "See Section 9.19 for these operators.) The GIN classes are listed."
    assert len(nlp_gold.draft(text)) == 1
    plain, found = nlp_gold.unmarked(text.replace(".) The", f".){MARK} The"))
    assert plain == text and [text[a:b] for a, b in found] == ["See Section 9.19 for these operators.)", "The GIN classes are listed."]


def test_naive_draft_splits_abbreviations_wrongly_so_it_is_only_a_draft():
    # The draft never decides gold: an ellipsis inside SQL is split and must be corrected by hand.
    assert len(nlp_gold.draft("Same as we'd get from SELECT ... WHERE unique1 < 10 here.")) == 2
    assert len(nlp_gold.draft("Use a small value, i.e. one that fits.")) == 1


def test_prose_paragraphs_are_whole_and_skip_headings_lists_code_and_labels():
    filler = "This sentence is long enough to count as prose for the sampler. "
    page = "\n\n".join(["## Heading", "- a list item " + filler, "Note", "    code block " + filler, filler * 3 + "End.",
                        "Chapter 3.\nAdvanced Features\n" + filler * 3, "1. numbered " + filler])
    found = list(nlp_gold.prose_paragraphs(page))
    assert [block for _, block in found] == [(filler * 3 + "End.")]
    start, block = found[0]
    assert page[start:start + len(block)] == block


@pytest.mark.parametrize("text, expected", [
    ("Run kafka-topics.sh to list topics.", True), ("The spark of an idea.", True), ("Kafka brokers replicate.", False),
    ("Apache Spark runs jobs.", False), ("Set spark.memory.fraction lower.", True),
])
def test_ambiguous_use_stratum(text, expected):
    assert nlp_gold.has_ambiguous_use(text, ["Kafka", "Spark", "Airflow"]) is expected


def test_label_normalization_is_nfkc_casefold_and_collapsed_whitespace():
    assert nlp_gold.normalized("Consumer   Group") == nlp_gold.normalized("consumer group") == "consumer group"
    assert nlp_gold.normalized("ＭＶＣＣ") == "mvcc"


def test_sample_order_is_seeded_and_stable():
    assert nlp_gold.order("abc") == nlp_gold.order("abc") != nlp_gold.order("abd")


class FakeCorpus:
    """Two technologies, three documents each, every chunk long enough to sample; one chunk per technology has an
    ambiguous use."""

    def __init__(self):
        self.documents, self.texts = [], {}
        for technology, name in (("Apache Kafka", "kafka"), ("PostgreSQL", "pg")):
            for number in range(3):
                key = f"{name}-{number}"
                self.documents.append({"source_key": key, "technology": technology, "format": "html"})
                words = "Run kafka-topics.sh to list topics. " if number == 0 else ""
                self.texts[key] = [(words + f"Plain prose for {key} chunk {{}}. " * 20).format(*range(20))] * 4

    def pages(self, document):
        return ["".join(self.texts[document["source_key"]])]

    def chunks(self, document):
        size = len(self.texts[document["source_key"]][0])
        return [{"document_index": 0, "start": i * size, "end": (i + 1) * size} for i in range(4)]


@pytest.fixture
def round_two():
    nlp_gold.use_round(2)
    yield
    nlp_gold.use_round(1)


def test_round_two_has_its_own_seed_folders_and_ids(round_two):
    assert nlp_gold.SEED != nlp_gold.ROUNDS[1]["seed"] and nlp_gold.GOLD.name == "round2" and nlp_gold.SHEETS.name == "round2"
    assert nlp_gold.order("abc") != nlp_gold.digest(f"{nlp_gold.ROUNDS[1]['seed']}|abc")
    corpus = FakeCorpus()
    # Round 2 asks for 8 per technology; three documents at two chunks each hold only 6.
    with pytest.raises(SystemExit):
        nlp_gold.sample_entities(corpus)
    nlp_gold.ENTITY_CHUNKS_PER_TECHNOLOGY = 4
    excluded = [("kafka-1", 0, 0, 10), ("pg-2", 0, 0, 10**6)]
    chosen = nlp_gold.sample_entities(corpus, excluded)
    assert [item["id"] for item in chosen] == [f"E{n}" for n in range(21, 29)]
    assert not any(nlp_gold.overlaps(item, excluded) for item in chosen)
    assert all(sum(other["source_key"] == item["source_key"] for other in chosen) <= 2 for item in chosen)
    assert all(any(item["ambiguous_stratum"] for item in chosen if item["technology"] == t) for t in ("Apache Kafka", "PostgreSQL"))


def test_round_two_key_terms_are_every_document_round_one_did_not_use(round_two, monkeypatch):
    monkeypatch.setattr(nlp_gold, "round_one_keyterm_sources", lambda: {"kafka-0", "pg-1"})
    chosen = nlp_gold.sample_keyterm_documents_round_two(FakeCorpus())
    assert [item["id"] for item in chosen] == ["K06", "K07", "K08", "K09"]
    assert {item["source_key"] for item in chosen} == {"kafka-1", "kafka-2", "pg-0", "pg-2"}
    assert [item["technology"] for item in chosen] == ["Apache Kafka"] * 2 + ["PostgreSQL"] * 2
