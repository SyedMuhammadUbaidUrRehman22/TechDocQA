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
