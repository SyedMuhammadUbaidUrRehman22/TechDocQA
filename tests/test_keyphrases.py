"""FR-08 keyphrases with RAKE (P9-5 as amended by the dependency gate): order, short text, determinism, no data download."""

import pytest

from techdocqa.enrichment import keyphrases
from techdocqa.settings import EnrichmentSettings

pytest.importorskip("rake_nltk")

SENTENCES = [
    "Apache Kafka stores records in partitions.",
    "The producer setting linger.ms adds a small delay so that records sent meanwhile are batched together.",
    "Each consumer group tracks committed offsets per partition.",
    "Brokers replicate partitions to followers, and the leader serves reads and writes.",
]


def test_ac_08_1_one_to_n_phrases_in_descending_score_with_technical_tokens_whole():
    found = keyphrases.ranked(SENTENCES, EnrichmentSettings(), 10)
    assert 1 <= len(found) <= 10
    scores = [score for _, score in found]
    assert scores == sorted(scores, reverse=True)
    assert any("linger.ms" in phrase for phrase, _ in found)
    assert all(phrase == phrase.lower() for phrase, _ in found)


@pytest.mark.parametrize("sentences", [["Kafka"], [], ["  "], ["Kafka brokers."], ["0.6 3.8.18 ,,, !!"]])
def test_ac_08_2_very_short_text_gives_an_empty_list_without_error(sentences):
    assert keyphrases.ranked(sentences, EnrichmentSettings(), 10) == []


def test_limit_and_minimum_words_are_configurable():
    assert len(keyphrases.ranked(SENTENCES, EnrichmentSettings(), 2)) == 2
    assert keyphrases.ranked(SENTENCES[:1], EnrichmentSettings(keyphrase_min_words=50), 10) == []


def test_phrases_never_exceed_the_word_limit_and_need_a_letter():
    found = keyphrases.ranked(SENTENCES + ["Version 3.8.18 shipped 0.6 0.7 0.8 values."], EnrichmentSettings(keyphrase_max_words=2), 50)
    assert found and all(len(phrase.split()) <= 2 for phrase, _ in found)
    assert all(any(char.isalpha() for char in phrase) for phrase, _ in found)


def test_equal_scores_are_ordered_by_phrase_and_runs_repeat_exactly():
    first = keyphrases.ranked(SENTENCES, EnrichmentSettings(), 50)
    assert first == keyphrases.ranked(list(SENTENCES), EnrichmentSettings(), 50)
    for (a_phrase, a_score), (b_phrase, b_score) in zip(first, first[1:]):
        assert a_score > b_score or (a_score == b_score and a_phrase < b_phrase)


def test_no_nltk_data_is_read_or_downloaded(tmp_path, monkeypatch):
    import nltk
    monkeypatch.setenv("NLTK_DATA", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("NLTK data access")
    monkeypatch.setattr(nltk.data, "find", forbidden)
    monkeypatch.setattr(nltk, "download", forbidden)
    assert keyphrases.ranked(SENTENCES, EnrichmentSettings(), 10)


def test_punctuation_splits_phrases_and_flags_stay_whole():
    tokens = keyphrases.tokens("Use --deploy-mode cluster (or client); see spark-submit - then stop.")
    assert "--deploy-mode" in tokens and "spark-submit" in tokens
    assert "-" not in tokens and "(" not in tokens and tokens.count(keyphrases.DELIMITER) >= 3


def test_masked_code_keeps_offsets_and_breaks_phrases():
    text = "Run the job.\nfor item in items: emit(item)\nThen stop."
    start = text.index("for")
    end = text.index("\nThen")
    masked = keyphrases.masked(text, [{"start": start, "end": end}])
    assert len(masked) == len(text) and "emit" not in masked and masked[start] == keyphrases.DELIMITER
    assert masked[:start] == text[:start] and masked[end:] == text[end:]


def test_config_id_follows_every_setting():
    base = keyphrases.config_id(EnrichmentSettings())
    for change in ({"keyphrases_per_document": 5}, {"keyphrases_per_chunk": True}, {"keyphrase_min_words": 3},
                   {"keyphrase_max_words": 3}, {"keyphrases_include_code": False}):
        assert keyphrases.config_id(EnrichmentSettings(**change)) != base
    assert keyphrases.config_id(EnrichmentSettings()) == base
