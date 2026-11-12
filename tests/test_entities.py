"""FR-07 rule-based entity extraction (P9-3, P9-12): gazetteer, context rule, overlaps, identifiers and regex bounds."""

from pathlib import Path
import time

import pytest

from techdocqa.enrichment import entities
from techdocqa.enrichment.entities import Gazetteer, context_keys, extract
from techdocqa.errors import TechDocQAError

GAZETTEER = Path(__file__).resolve().parents[1] / "config" / "gazetteer.toml"


@pytest.fixture(scope="module")
def gazetteer():
    return Gazetteer(GAZETTEER)


def found(text, gazetteer, technology=None, documents=None):
    context = context_keys(documents or [text], gazetteer, technology)
    return [(m.text, m.type, m.rule_id, m.confidence) for m in extract(text, gazetteer, context)]


def test_ac_07_1_five_gazetteer_entities_with_their_types(gazetteer):
    text = "Apache Kafka feeds Redis and PostgreSQL over HTTP; each consumer group tracks its position."
    kinds = {(text, kind) for text, kind, _, _ in found(text, gazetteer)}
    assert {("Apache Kafka", "TECHNOLOGY"), ("Redis", "TECHNOLOGY"), ("PostgreSQL", "TECHNOLOGY"),
            ("consumer group", "CONCEPT"), ("HTTP", "PROTOCOL")} <= kinds


def test_exact_gazetteer_match_is_confidence_one_and_offsets_slice_back(gazetteer):
    text = "We run PostgreSQL."
    [mention] = extract(text, gazetteer, set())
    assert (mention.confidence, mention.rule_id, text[mention.start:mention.end]) == (1.0, "gazetteer", "PostgreSQL")
    assert mention.key == "postgresql"


def test_ambiguous_alias_needs_its_context_rule(gazetteer):
    # VULN-01: a bare ambiguous name is stored below the 0.5 threshold, so it is never verified.
    assert found("Kafka wrote about trials.", gazetteer) == [("Kafka", "TECHNOLOGY", "gazetteer-ambiguous", 0.4)]
    # The document's user technology names the entry.
    assert found("Kafka stores records.", gazetteer, "Apache Kafka")[0][2:] == ("gazetteer", 1.0)
    # Or an unambiguous alias occurs elsewhere in the same document.
    assert found("Spark runs jobs.", gazetteer, documents=["Spark runs jobs.", "Apache Spark is fast."])[0][2:] == ("gazetteer", 1.0)
    # Case-sensitive entries do not match lowercase words.
    assert found("a spark of light", gazetteer) == []


def test_components_hold_where_their_technology_holds(gazetteer):
    assert ("topics", "CONCEPT", "gazetteer-ambiguous", 0.4) in found("Read the topics.", gazetteer)
    assert ("topics", "CONCEPT", "gazetteer", 1.0) in found("Read the topics.", gazetteer, "Apache Kafka")
    assert ("topics", "CONCEPT", "gazetteer", 1.0) in found("Apache Kafka keeps topics.", gazetteer)
    assert ("driver", "COMPONENT", "gazetteer-ambiguous", 0.4) in found("A JDBC driver connects.", gazetteer)
    assert ("driver", "COMPONENT", "gazetteer", 1.0) in found("The driver plans stages.", gazetteer, "Apache Spark")


def test_longest_match_wins_and_inner_names_are_not_separate_mentions(gazetteer):
    text = "Run kafka-topics.sh, set spark.memory.fraction, then Apache Kafka and a consumer group."
    mentions = found(text, gazetteer, "Apache Kafka")
    texts = [item[0] for item in mentions]
    assert "kafka-topics.sh" in texts and "spark.memory.fraction" in texts
    assert "Apache Kafka" in texts and "Kafka" not in texts
    assert "consumer group" in texts and "consumer" not in texts
    spans = [(m.start, m.end) for m in extract(text, gazetteer, context_keys([text], gazetteer, "Apache Kafka"))]
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:]))


def test_protocols_are_whole_and_beat_an_identifier_of_equal_length(gazetteer):
    assert found("Clients negotiate HTTP/2 over TLS.", gazetteer) == [("HTTP/2", "PROTOCOL", "protocol", 0.9),
                                                                      ("TLS", "PROTOCOL", "protocol", 0.9)]


@pytest.mark.parametrize("token, rule", [
    ("linger.ms", "identifier"), ("max_poll_records", "identifier"), ("--deploy-mode", "identifier"),
    ("pg_subtrans", "identifier"), ("std::vector", "identifier"), ("maxMemoryPolicy", "identifier-camel"),
    ("e.g", None), ("i.e", None), ("3.8.18", None), ("0.6", None), ("https://kafka.apache.org/43", None),
    ("read-only", None), ("Kafka", None), ("plain", None),
])
def test_identifier_rules(token, rule):
    assert entities.identifier_rule(token) == rule


def test_urls_versions_and_abbreviations_yield_no_identifier(gazetteer):
    text = "See https://kafka.apache.org/43/ for version 3.8.18, e.g. the 0.6 default."
    assert [item for item in found(text, gazetteer) if item[1] == "IDENTIFIER"] == []


def test_identifier_token_is_the_bm25_technical_token():
    from techdocqa.retrieval.lexical import TECHNICAL
    assert entities.TOKEN.pattern == TECHNICAL.pattern


@pytest.mark.parametrize("unit", ["a.", "--", "a_", "a-", "HTTP/", "Kafka ", "x", ".:/#+-", "aB"],
                         ids=["dots", "dashes", "underscores", "hyphens", "protocol", "alias", "word", "separators", "camel"])
def test_patterns_finish_in_bounded_time_on_adversarial_input(gazetteer, unit):
    # P9-12: repetition only over disjoint classes, so time grows linearly. Five times the input must cost well under
    # the 25 times a quadratic pattern would; 100,000 characters stay within a few seconds on a slow machine.
    # Best of three runs per size, so a pause from another process on a loaded machine does not count as growth.
    def elapsed(length):
        text = unit * (length // len(unit))
        times = []
        for _ in range(3):
            started = time.perf_counter()
            extract(text, gazetteer, context_keys([text], gazetteer, None))
            times.append(time.perf_counter() - started)
        return min(times)
    small, large = elapsed(20_000), elapsed(100_000)
    assert large < 3.0 and large < 12 * max(small, 0.005)


@pytest.mark.parametrize("body", [
    'version = "v"\n[[entities]]\nname = "A"\ntype = "TECHNOLOGY"\naliases = ["A"]\n[[entities]]\nname = "B"\ntype = "TECHNOLOGY"\naliases = ["B", "a"]\n',
    'version = "v"\n[[entities]]\nname = "A"\ntype = "TECHNOLOGY"\naliases = ["A"]\nambiguous = ["Z"]\n',
    'version = "v"\n[[entities]]\nname = "A"\ntype = "TECHNOLOGY"\naliases = ["B"]\n',
    'version = "v"\n[[entities]]\nname = "A"\ntype = "WIDGET"\naliases = ["A"]\n',
    'version = "v"\n[[entities]]\nname = "A"\ntype = "TECHNOLOGY"\naliases = [" A"]\n',
    'not toml [',
])
def test_invalid_gazetteers_are_configuration_errors(tmp_path, body):
    path = tmp_path / "gazetteer.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(TechDocQAError) as error:
        Gazetteer(path)
    assert error.value.response.error.code == "INVALID_CONFIGURATION"


def test_missing_gazetteer_is_a_configuration_error(tmp_path):
    with pytest.raises(TechDocQAError) as error:
        Gazetteer(tmp_path / "absent.toml")
    assert error.value.response.error.code == "INVALID_CONFIGURATION"


def test_config_id_follows_the_gazetteer_bytes_and_threshold(tmp_path, gazetteer):
    copy = tmp_path / "g.toml"
    copy.write_bytes(GAZETTEER.read_bytes())
    same = Gazetteer(copy)
    assert entities.config_id(same, 0.5) == entities.config_id(gazetteer, 0.5) != entities.config_id(gazetteer, 0.6)
    copy.write_bytes(GAZETTEER.read_bytes() + b"\n# edited\n")
    assert entities.config_id(Gazetteer(copy), 0.5) != entities.config_id(gazetteer, 0.5)


def test_filter_key_resolves_aliases_case_blind(gazetteer):
    assert gazetteer.filter_key("kafka") == gazetteer.filter_key("Apache Kafka") == "apache kafka"
    assert gazetteer.filter_key("linger.ms") == "linger.ms"


def test_a_file_given_with_a_directory_is_labeled_by_its_name(gazetteer):
    text = "Run bin/kafka-topics.sh --create, then edit config/server.properties."
    mentions = extract(text, gazetteer, context_keys([text], gazetteer, "Apache Kafka"))
    assert [(m.text, m.type) for m in mentions] == [("kafka-topics.sh", "IDENTIFIER"), ("--create", "IDENTIFIER"),
                                                    ("server.properties", "IDENTIFIER")]
    assert all(text[m.start:m.end] == m.text for m in mentions)
    # A URL is never cut down to its last segment.
    assert found("See https://kafka.apache.org/docs/a.html now.", gazetteer) == []


def test_upper_case_sql_keywords_are_identifiers_inside_a_statement(gazetteer):
    text = "Run SELECT name FROM users WHERE id = 1 ORDER  BY name;"
    sql = [(m.text, m.canonical, m.rule_id, m.confidence) for m in extract(text, gazetteer, set()) if m.rule_id == "sql-keyword"]
    assert sql == [("SELECT", "SELECT", "sql-keyword", 0.8), ("FROM", "FROM", "sql-keyword", 0.8),
                   ("WHERE", "WHERE", "sql-keyword", 0.8), ("ORDER  BY", "ORDER BY", "sql-keyword", 0.8)]
    # A multi-word unit counts on its own, also at the end of a sentence; a stray upper-case AND or OR does not.
    assert found("Use AND or OR carefully. Sort with ORDER BY.", gazetteer) == [("ORDER BY", "IDENTIFIER", "sql-keyword", 0.8)]
    assert found("select the rows from the table", gazetteer) == []
    assert [item[0] for item in found("Set SET.x and SELECT-like.", gazetteer)] == ["SET.x"]


def test_gazetteer_types_follow_the_guidelines_type_table(gazetteer):
    spark = found("Submit with spark-submit and a SparkConf; an RDD and a DataFrame.", gazetteer, "Apache Spark")
    assert [(text, kind) for text, kind, _, _ in spark] == [("spark-submit", "IDENTIFIER"), ("SparkConf", "IDENTIFIER"),
                                                            ("RDD", "CONCEPT"), ("DataFrame", "CONCEPT")]
    postgres = found("Run VACUUM; autovacuum runs it too. EXPLAIN shows a B-tree plan.", gazetteer, "PostgreSQL")
    assert [(text, kind) for text, kind, _, _ in postgres] == [("VACUUM", "IDENTIFIER"), ("autovacuum", "COMPONENT"),
                                                               ("EXPLAIN", "IDENTIFIER"), ("B-tree", "CONCEPT")]
    # A sensor is a named abstraction only where Airflow holds.
    assert ("sensors", "CONCEPT", "gazetteer-ambiguous", 0.4) in found("Motion sensors fire.", gazetteer)
