"""FR-08 keyphrases: the technical n-gram policy (the default) and RAKE (P9-5 as amended by the dependency gate):
order, short text, determinism, no data download."""

import sys

import pytest

from techdocqa.enrichment import keyphrases
from techdocqa.settings import EnrichmentSettings

SENTENCES = [
    "Apache Kafka stores records in partitions.",
    "The producer setting linger.ms adds a small delay so that records sent meanwhile are batched together.",
    "Each consumer group tracks committed offsets per partition.",
    "Brokers replicate partitions to followers, and the leader serves reads and writes.",
]
NGRAM = EnrichmentSettings()


def rake_settings(**changes):
    pytest.importorskip("rake_nltk")
    return EnrichmentSettings(keyphrase_policy="rake", **changes)


@pytest.mark.parametrize("policy", ["ngram", "rake"])
def test_ac_08_1_one_to_n_phrases_in_descending_score_with_technical_tokens_whole(policy):
    settings = NGRAM if policy == "ngram" else rake_settings()
    found = keyphrases.ranked(SENTENCES, settings, 10 if policy == "rake" else 50)
    assert 1 <= len(found) <= (10 if policy == "rake" else 50)
    scores = [score for _, score in found]
    assert scores == sorted(scores, reverse=True)
    assert any("linger.ms" in phrase for phrase, _ in found)


@pytest.mark.parametrize("policy", ["ngram", "rake"])
@pytest.mark.parametrize("sentences", [["Kafka"], [], ["  "], ["Kafka brokers."], ["0.6 3.8.18 ,,, !!"]])
def test_ac_08_2_very_short_text_gives_an_empty_list_without_error(policy, sentences):
    settings = NGRAM if policy == "ngram" else rake_settings()
    assert keyphrases.ranked(sentences, settings, 10) == []


@pytest.mark.parametrize("policy", ["ngram", "rake"])
def test_limit_and_minimum_words_are_configurable(policy):
    settings = NGRAM if policy == "ngram" else rake_settings()
    assert len(keyphrases.ranked(SENTENCES, settings, 2)) == 2
    fewer = settings.model_copy(update={"keyphrase_min_words": 50})
    assert keyphrases.ranked(SENTENCES[:1], fewer, 10) == []


def test_rake_phrases_never_exceed_the_word_limit_and_need_a_letter():
    found = keyphrases.ranked(SENTENCES + ["Version 3.8.18 shipped 0.6 0.7 0.8 values."], rake_settings(keyphrase_max_words=2), 50)
    assert found and all(len(phrase.split()) <= 2 for phrase, _ in found)
    assert all(any(char.isalpha() for char in phrase) for phrase, _ in found)
    assert all(phrase == phrase.lower() for phrase, _ in found)


def test_rake_equal_scores_are_ordered_by_phrase_and_runs_repeat_exactly():
    settings = rake_settings()
    first = keyphrases.ranked(SENTENCES, settings, 50)
    assert first == keyphrases.ranked(list(SENTENCES), settings, 50)
    for (a_phrase, a_score), (b_phrase, b_score) in zip(first, first[1:]):
        assert a_score > b_score or (a_score == b_score and a_phrase < b_phrase)


def test_ngram_terms_have_one_or_two_words_a_letter_and_no_filler():
    found = keyphrases.ranked(SENTENCES + ["Version 3.8.18 shipped 0.6 0.7 0.8 values.", "See the following example."], NGRAM, 50)
    assert found and all(1 <= len(phrase.split()) <= 2 for phrase, _ in found)
    assert all(any(char.isalpha() for char in phrase) for phrase, _ in found)
    folded = {phrase.casefold() for phrase, _ in found}
    assert not folded & {"following", "example", "values", "see"}


def test_ngram_short_terms_inside_long_runs_still_count():
    # RAKE scores only whole runs, so "consumer group" inside a longer run never appears; here it is the top term.
    sentences = ["Each consumer group offset commit protocol message is small.", "A consumer group rebalances.",
                 "The consumer group coordinator tracks members."]
    assert keyphrases.ranked(sentences, NGRAM, 1)[0][0] == "consumer group"


def test_ngram_plural_forms_are_one_term_shown_in_the_most_frequent_form():
    found = dict(keyphrases.ranked(["Tasks run.", "The tasks retry.", "A task waits.", "Tasks finish."], NGRAM, 10))
    assert "Tasks" in found and "task" not in found and "tasks" not in found


def test_ngram_drops_the_technology_name_alone_but_not_inside_a_term():
    sentences = ["Kafka stores records.", "Kafka Streams reads them.", "Kafka Streams writes them.", "Kafka runs."]
    found = [phrase for phrase, _ in keyphrases.ranked(sentences, NGRAM, 10, exclude=frozenset({"kafka", "apache kafka"}))]
    assert "Kafka" not in found and "Kafka Streams" in found


def test_ngram_a_word_mostly_inside_a_listed_term_is_dropped():
    sentences = ["The Dag bundle holds files.", "A Dag bundle is versioned.", "Each Dag bundle syncs.", "The bundle is new."]
    found = [phrase for phrase, _ in keyphrases.ranked(sentences, NGRAM, 10)]
    assert "Dag bundle" in found and "bundle" not in found


def test_ngram_gazetteer_terms_rank_above_equally_frequent_words():
    sentences = ["The scheduler and the queue.", "Each scheduler, each queue."]
    plain = [phrase for phrase, _ in keyphrases.ranked(sentences, NGRAM, 2)]
    boosted = [phrase for phrase, _ in keyphrases.ranked(sentences, NGRAM, 2, domain=frozenset({"queue"}))]
    assert plain[0] == "scheduler" and boosted[0] == "queue"


def test_ngram_equal_scores_go_to_the_earlier_term_and_runs_repeat_exactly():
    assert keyphrases.ranked(["The zebra, the alpha, the mango."], NGRAM, 10) == [("zebra", 1.0), ("alpha", 1.0), ("mango", 1.0)]
    first = keyphrases.ranked(SENTENCES, NGRAM, 50)
    assert first == keyphrases.ranked(list(SENTENCES), NGRAM, 50)
    scores = [score for _, score in first]
    assert scores == sorted(scores, reverse=True)


def test_ngram_needs_neither_rake_nor_nltk(monkeypatch):
    monkeypatch.setitem(sys.modules, "rake_nltk", None)
    monkeypatch.setattr(keyphrases, "rake_version", lambda: None)
    assert keyphrases.available(NGRAM) and not keyphrases.available(EnrichmentSettings(keyphrase_policy="rake"))
    assert keyphrases.ranked(SENTENCES, NGRAM, 10)


def test_no_nltk_data_is_read_or_downloaded(tmp_path, monkeypatch):
    settings = rake_settings()
    import nltk
    monkeypatch.setenv("NLTK_DATA", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("NLTK data access")
    monkeypatch.setattr(nltk.data, "find", forbidden)
    monkeypatch.setattr(nltk, "download", forbidden)
    assert keyphrases.ranked(SENTENCES, settings, 10)


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


def test_config_id_follows_every_setting_that_applies_to_the_policy():
    base = keyphrases.config_id(NGRAM, "a" * 64)
    for change in ({"keyphrases_per_document": 5}, {"keyphrases_per_chunk": True}, {"keyphrase_min_words": 3},
                   {"keyphrases_include_code": False}, {"keyphrase_policy": "rake"}):
        assert keyphrases.config_id(EnrichmentSettings(**change), "a" * 64) != base
    # The n-gram policy reads the gazetteer, and ignores RAKE's own settings.
    assert keyphrases.config_id(NGRAM, "b" * 64) != base
    assert keyphrases.config_id(EnrichmentSettings(keyphrase_max_words=3, keyphrase_metric="word_degree"), "a" * 64) == base
    rake = EnrichmentSettings(keyphrase_policy="rake")
    for change in ({"keyphrase_max_words": 3}, {"keyphrase_metric": "word_degree"}):
        assert keyphrases.config_id(rake.model_copy(update=change)) != keyphrases.config_id(rake)
    assert keyphrases.config_id(NGRAM, "a" * 64) == base
