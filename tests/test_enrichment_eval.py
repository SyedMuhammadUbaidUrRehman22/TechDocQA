"""eval --enrichment (Phase 9 step 8): metrics, gold-set scoring, the unclassified threshold proposal, real-corpus checks
and the read-only guarantee, offline with the word-hash fake embedder."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from techdocqa.cli import main
from techdocqa.enrichment import classification, entities, keyphrases
from techdocqa.enrichment.entities import Mention
from techdocqa.enrichment.pipeline import embedding_profile_or_none, enrich_versions
from techdocqa.evaluation import enrichment as evaluation
from techdocqa.evaluation.runner import load_manifest
from techdocqa.indexing.pipeline import index_versions
from techdocqa.ingestion.processing import finalized_documents
from techdocqa.settings import CategorySpec, EnrichmentSettings

from test_enrichment import GAZETTEER
from test_indexing import embedder, ingest, inline_workers, model_settings  # noqa: F401

CATEGORIES = [
    CategorySpec(name="Distributed streaming", description="Kafka brokers replicate topic partitions for producers and consumers."),
    CategorySpec(name="Databases", description="PostgreSQL transaction isolation keeps tables and indexes consistent."),
    CategorySpec(name="Caching", description="Redis keeps keys in memory and evicts cached values."),
]
DOCUMENTS = {
    "kafka1.md": ("Apache Kafka", "Distributed streaming", "Apache Kafka brokers replicate topic partitions for consumers. "),
    "kafka2.md": ("Apache Kafka", "Distributed streaming", "Kafka producers write records to topic partitions on brokers. "),
    "pg1.md": ("PostgreSQL", "Databases", "PostgreSQL transaction isolation keeps tables and indexes consistent. "),
    "pg2.md": ("PostgreSQL", "Databases", "PostgreSQL indexes speed up queries over tables in a transaction. "),
    "redis1.md": ("Redis", "Caching", "Redis keeps keys in memory and evicts cached values by policy. "),
    "redis2.md": ("Redis", "Caching", "Cached values in Redis memory expire, and Redis evicts old keys. "),
}
PASSAGE = "See Fig. 3 for the plan. Then run it."
FIXTURES = [
    ("oot-a", "calibration", "gardening", "Water tomato seedlings each morning and pinch out side shoots. "),
    ("oot-b", "calibration", "chess", "Develop knights and bishops early, then castle the king. "),
    ("oot-c", "held_out", "cooking", "Whisk eggs with sugar, fold in flour and bake the cake. "),
    ("oot-d", "held_out", "birdwatching", "Robins sing in winter while wrens trill from the hedge. "),
]


def write_jsonl(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.fixture
def eval_settings(model_settings):
    model_settings.enrichment = EnrichmentSettings(gazetteer=str(GAZETTEER), categories=CATEGORIES)
    return model_settings


@pytest.fixture
def setup(corpus, eval_settings, registry, embedder, tmp_path):
    versions = {}
    for name, (technology, category, sentence) in DOCUMENTS.items():
        body = f"# {technology} notes\n\n" + sentence * 12 + ("\n\n" + PASSAGE + "\n\nAnother paragraph closes it." if name == "pg1.md" else "")
        (corpus / name).write_text(body, encoding="utf-8")
        versions[name] = ingest(corpus / name, eval_settings, registry, technology=technology, category=category)
    (corpus / "private.md").write_text("# Private\n\n" + "PostgreSQL private notes about indexes and tables. " * 12, encoding="utf-8")
    private = ingest(corpus / "private.md", eval_settings, registry, technology="PostgreSQL")
    assert index_versions([], eval_settings, registry).run.failed == 0
    keys = {name: registry.get_document(version.document_id).source_key for name, version in versions.items()}
    manifest = {"dataset_id": "test-reference", "status": "frozen", "reference_fingerprint_sha256": "0" * 64, "documents": [
        {"source_key": keys[name], "document_id": version.document_id, "evaluation_included": True, "format": "md",
         "technology": DOCUMENTS[name][0], "content_hash": registry.get_version(version.version_id).content_hash}
        for name, version in versions.items()] + [
        {"source_key": registry.get_document(private.document_id).source_key, "document_id": private.document_id,
         "evaluation_included": False, "format": "md", "content_hash": "x"}]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    gold = tmp_path / "gold"
    gold.mkdir()
    write_jsonl(gold / "out_of_topic.jsonl", [{"id": i, "split": split, "topic": topic, "title": topic, "text": f"# {topic}\n\n" + text * 10}
                                              for i, split, topic, text in FIXTURES])
    return {"versions": versions, "keys": keys, "manifest": manifest_path, "gold": gold, "private": private}


def page_of(setup, settings, registry, name):
    return finalized_documents(setup["versions"][name].version_id, settings, registry)[0].page_content


def segmentation_gold(setup, settings, registry):
    page = page_of(setup, settings, registry, "pg1.md")
    start = page.index(PASSAGE)
    first = len("See Fig. 3 for the plan.")
    return write_jsonl(setup["gold"] / "segmentation_gold.jsonl", [{
        "id": "S01", "source_key": setup["keys"]["pg1.md"], "technology": "PostgreSQL", "format": "md", "document_index": 0,
        "start": start, "end": start + len(PASSAGE), "text_sha256": hashlib.sha256(PASSAGE.encode()).hexdigest(),
        "anchor": PASSAGE[:40], "sentences": [[0, first], [first + 1, len(PASSAGE)]]}])


def table_counts(registry) -> dict:
    tables = [row[0] for row in registry.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    return {name: registry.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}


# Metrics

def test_wilson_interval_and_verdicts():
    assert evaluation.wilson(8, 10) == {"low": 0.4902, "high": 0.9433}
    assert evaluation.wilson(0, 0) is None and evaluation.wilson(10, 10)["high"] == 1.0
    assert evaluation.rate(3, 4) == {"value": 0.75, "numerator": 3, "denominator": 4, "interval": evaluation.wilson(3, 4)}
    # A target met only at the point estimate is reported that way (VULN-04).
    assert evaluation.verdict(0.9, 0.86, 0.85) == "met"
    assert evaluation.verdict(0.9, 0.6, 0.85) == "met_at_point_estimate_only"
    assert evaluation.verdict(0.8, 0.6, 0.85) == "not_met" and evaluation.verdict(None, None, 0.85) == "not_measured"
    assert evaluation.f1(0.5, 1.0) == pytest.approx(2 / 3, abs=1e-6) and evaluation.f1(0.0, 0.0) == 0.0


def test_gold_comparison_form_matches_the_guidelines():
    assert evaluation.normalized("Consumer   Group") == "consumer group" and evaluation.normalized("ＭＶＣＣ") == "mvcc"


# Gold-set scoring

def test_boundaries_are_scored_per_policy_at_exact_positions(setup, eval_settings, registry):
    segmentation_gold(setup, eval_settings, registry)
    gold = evaluation.gold_sets(setup["gold"])
    scope = evaluation.Scope(load_manifest(setup["manifest"]), eval_settings, registry)
    result = evaluation.score_segmentation(gold["segmentation"], scope)
    rules, spacy = result["policies"]["rules"], result["policies"]["spacy"]
    # The P0 rules split after "Fig."; the spaCy policy's abbreviation rule does not.
    assert (rules["precision"]["numerator"], rules["precision"]["denominator"], rules["recall"]["value"]) == (1, 2, 1.0)
    assert [error["kind"] for error in rules["errors"]] == ["spurious"] and "Fig.|" in rules["errors"][0]["context"].replace(" ", "")
    assert spacy["boundary_f1"] == 1.0 and spacy["exact_sentences"]["value"] == 1.0 and not spacy["errors"]
    assert result["spacy_beats_rules"] and spacy["verdict"] == "too_few_sentences" and result["ac_06_4"] == "too_few_sentences"


def test_a_gold_span_whose_text_changed_is_flagged_not_scored(setup, eval_settings, registry):
    path = segmentation_gold(setup, eval_settings, registry)
    row = json.loads(path.read_text(encoding="utf-8"))
    write_jsonl(path, [{**row, "text_sha256": "0" * 64}])
    scope = evaluation.Scope(load_manifest(setup["manifest"]), eval_settings, registry)
    result = evaluation.score_segmentation(evaluation.gold_sets(setup["gold"])["segmentation"], scope)
    assert result["flagged"] == ["S01"] and result["passages"] == 0


class FakeScope:
    def __init__(self, texts, technology="PostgreSQL"):
        self.texts = texts
        record = SimpleNamespace(technology=technology)
        self.records = {"doc": record}
        self.data = {"record": record, "data": {"chunks": [{"text": text} for text in texts.values()]}}

    def span(self, row):
        return self.texts.get(row["id"])

    def load(self, key):
        return self.data


def mention(text, kind, rule="gazetteer", confidence=1.0, start=0):
    return Mention(text, text, kind, rule, confidence, start, start + len(text))


def test_entity_precision_and_recall_on_normalized_text_and_type(eval_settings, monkeypatch):
    found = {"E01": [mention("PostgreSQL", "TECHNOLOGY"), mention("MVCC", "CONCEPT"), mention("linger.ms", "IDENTIFIER", "identifier", 0.8),
                     mention("Kafka", "TECHNOLOGY", "gazetteer-ambiguous", 0.4)],
             "E02": [mention("WAL", "COMPONENT")]}
    texts = {"E01": "chunk one", "E02": "chunk two"}
    monkeypatch.setattr(entities, "extract", lambda text, gazetteer, context: found["E01" if text == "chunk one" else "E02"])
    rows = [{"id": "E01", "source_key": "doc", "technology": "PostgreSQL", "format": "md", "ambiguous_stratum": True,
             "mentions": [{"text": "postgresql", "normalized": "postgresql", "type": "TECHNOLOGY"},
                          {"text": "MVCC", "normalized": "mvcc", "type": "IDENTIFIER"},
                          {"text": "Kafka", "normalized": "kafka", "type": "TECHNOLOGY"}]},
            {"id": "E02", "source_key": "doc", "technology": "PostgreSQL", "format": "pdf", "ambiguous_stratum": False,
             "mentions": [{"text": "WAL", "normalized": "wal", "type": "COMPONENT"}]}]
    result = evaluation.score_entities({"status": "frozen", "rows": rows}, FakeScope(texts), eval_settings)
    # Verified: PostgreSQL, MVCC (wrong type), linger.ms, WAL. The unverified Kafka candidate never counts as output.
    assert (result["precision"]["numerator"], result["precision"]["denominator"]) == (2, 4)
    assert (result["recall"]["numerator"], result["recall"]["denominator"]) == (2, 4)
    assert result["by_type"]["CONCEPT"]["precision"]["value"] == 0.0 and result["by_type"]["IDENTIFIER"]["recall"]["value"] == 0.0
    assert result["by_rule"]["pattern"]["precision"]["denominator"] == 1
    assert result["diagnostics"]["text_only"]["precision"] == 0.75
    assert result["diagnostics"]["including_unverified"]["recall"] == 0.75
    errors = {error["chunk"]: error for error in result["errors"]}
    assert {item["text"] for item in errors["E01"]["false_positives"]} == {"MVCC", "linger.ms"}
    assert next(item for item in errors["E01"]["false_positives"] if item["text"] == "MVCC")["gold_type"] == "IDENTIFIER"
    assert result["ac_07_4"] == "too_few_chunks" and not result["tuned"]


def test_a_gazetteer_changed_after_sampling_marks_the_entity_set_tuned(eval_settings, monkeypatch):
    monkeypatch.setattr(entities, "extract", lambda *args: [])
    rows = [{"id": "E01", "source_key": "doc", "technology": "x", "format": "md", "gazetteer_sha256": "0" * 64, "mentions": []}]
    assert evaluation.score_entities({"status": "frozen", "rows": rows}, FakeScope({"E01": "text"}), eval_settings)["tuned"]


def key_term_scope_and_rows():
    scope = FakeScope({})
    scope.data["documents"], scope.data["data"]["sentence_spans"] = [], []
    rows = [{"id": "K1", "source_key": "doc", "technology": "Kafka", "format": "html", "chunks": 3,
             "terms": ["log compaction", "linger.ms", "consumer", "retention"]}]
    return scope, rows


def test_key_terms_score_exact_hits_in_the_top_ten_for_every_variant(eval_settings, monkeypatch):
    seen = []
    def ranked(sentences, enrichment, limit, *, exclude, domain):
        seen.append((enrichment.keyphrase_policy, exclude, "log compaction" in domain))
        with_code = any("code" in sentence for sentence in sentences)
        found = [("Log Compaction", 3.0), ("consumer group", 2.0)] + ([("linger.ms", 1.0)] if with_code else [])
        if enrichment.keyphrase_policy == "ngram":
            return found + [("consumer", 1.5), ("retention", 1.0)]
        return found + [("retention", 0.5)] if enrichment.keyphrase_metric == "word_frequency" else found
    monkeypatch.setattr(keyphrases, "ranked", ranked)
    monkeypatch.setattr(keyphrases, "rake_version", lambda: "1.0.4")
    monkeypatch.setattr(keyphrases, "document_sentences", lambda documents, spans, include_code: ["code"] if include_code else ["prose"])
    scope, rows = key_term_scope_and_rows()
    rake = eval_settings.model_copy(update={"enrichment": eval_settings.enrichment.model_copy(update={"keyphrase_policy": "rake"})})
    result = evaluation.score_keyphrases({"status": "frozen", "rows": rows}, scope, rake)
    codes = ("with_code", "without_code")
    assert set(result["variants"]) == {f"{name}/{code}" for name in keyphrases.METRICS + ("ngram",) for code in codes}
    configured = result["variants"]["degree_to_frequency/with_code"]
    assert result["configured"] == "degree_to_frequency/with_code" and configured["mean_hit_rate"] == 0.5
    assert result["variants"]["degree_to_frequency/without_code"]["mean_hit_rate"] == 0.25
    # "consumer" is inside "consumer group": a lenient hit, reported only as a diagnostic.
    assert configured["mean_lenient_hit_rate"] == 0.75 and configured["documents"][0]["missed"] == ["consumer", "retention"]
    assert result["best_variant"] == "ngram/with_code" and result["ac_08_3"] == "too_few_documents" and not result["tuned"]
    assert configured["by_size"] == {"30 chunks or fewer": {"documents": 1, "mean_hit_rate": 0.5}}
    ngram = result["variants"]["ngram/with_code"]
    assert ngram["policy"] == keyphrases.NGRAM_POLICY and ngram["metric"] is None and ngram["mean_hit_rate"] == 1.0
    # Every variant gets the document's technology names and the gazetteer's terms.
    assert {policy for policy, _, _ in seen} == {"ngram", "rake"}
    assert all(exclude == frozenset({"postgresql", "postgres"}) and boosted for _, exclude, boosted in seen)


def test_key_terms_without_rake_score_the_ngram_policy_alone(eval_settings, monkeypatch):
    monkeypatch.setattr(keyphrases, "rake_version", lambda: None)
    monkeypatch.setattr(keyphrases, "ranked", lambda sentences, enrichment, limit, **kwargs: [("log compaction", 1.0)])
    monkeypatch.setattr(keyphrases, "document_sentences", lambda documents, spans, include_code: ["prose"])
    scope, rows = key_term_scope_and_rows()
    result = evaluation.score_keyphrases({"status": "frozen", "rows": rows}, scope, eval_settings)
    assert result["configured"] == "ngram/with_code" and set(result["variants"]) == {"ngram/with_code", "ngram/without_code"}
    assert result["variants"]["ngram/with_code"]["mean_hit_rate"] == 0.25
    # The round-1 key-term set is where the n-gram constants were chosen, so a score on it is reported as tuned.
    development = {"status": "frozen", "rows": rows, "sha256": next(iter(keyphrases.NGRAM_DEVELOPMENT_SETS))}
    assert evaluation.score_keyphrases(development, scope, eval_settings)["tuned"]


def test_key_term_tokens_drop_clitics_and_emphasis_but_keep_names():
    assert keyphrases.tokens("Don't stop; Kafka's log isn't _really_ slow, we’re told.") == [
        ",", "stop", ",", "Kafka", "log", ",", "really", "slow", ",", ",", "told", ","]
    assert keyphrases.tokens("See __init__.py, retry_after and --batch-size.") == [
        "See", "__init__.py", ",", "retry_after", "and", "--batch-size", ","]


def test_missing_gold_data_is_reported_as_awaiting_never_guessed(tmp_path):
    gold = evaluation.gold_sets(tmp_path)
    assert {item["status"] for item in gold.values()} == {"awaiting_gold_data"}
    assert evaluation.score_entities(gold["entities"], None, None) == {"status": "awaiting_gold_data"}


# Classification, the threshold and the corpus checks

def test_classification_proposes_a_threshold_and_judges_held_out_fixtures(setup, eval_settings, registry, embedder):
    before = table_counts(registry)
    report = evaluation.run_enrichment_evaluation(setup["manifest"], setup["gold"], eval_settings, registry)
    section = report["classification"]
    assert section["status"] == "scored" and section["active_threshold"]["status"] == "not_calibrated"
    assert {row["source_key"] for row in section["documents"]} == set(setup["keys"].values())
    proposal = section["proposal"]
    assert proposal["separable"] and proposal["calibration_out_of_topic"] == 2 and proposal["in_topic"] == len(DOCUMENTS)
    assert proposal["similarity_config_id"] == classification.similarity_config_id(eval_settings.enrichment,
                                                                                     embedding_profile_or_none(eval_settings))
    assert section["ac_09_1"]["top1_accuracy"]["value"] == 1.0 and section["ac_09_1"]["threshold_source"] == "proposal"
    assert section["ac_09_2"]["cooking_unclassified"] and section["ac_09_2"]["verdict"] == "met"
    assert all(row["chunks"] >= 1 for row in section["fixtures"])
    # Read-only: description and fixture vectors were computed in memory; nothing was written.
    assert table_counts(registry) == before
    assert report["corpus_checks"] == {"status": "not_run", "reason": "ENRICHMENT_NOT_CURRENT",
                                       "enrichment": {key: "not_enriched" for key in setup["keys"].values()}}


def test_an_adopted_threshold_is_the_one_judged(setup, eval_settings, registry, embedder):
    first = evaluation.run_enrichment_evaluation(setup["manifest"], setup["gold"], eval_settings, registry)
    proposal = first["classification"]["proposal"]
    eval_settings.enrichment = EnrichmentSettings(gazetteer=str(GAZETTEER), categories=CATEGORIES,
                                                  unclassified_threshold=proposal["unclassified_threshold"],
                                                  calibration_run_id=first["run_id"], similarity_config_id=proposal["similarity_config_id"])
    section = evaluation.run_enrichment_evaluation(setup["manifest"], setup["gold"], eval_settings, registry)["classification"]
    assert section["active_threshold"] == {"status": "calibrated", "unclassified_threshold": proposal["unclassified_threshold"],
                                           "calibration_run_id": first["run_id"]}
    assert section["ac_09_1"]["threshold_source"] == "active" and section["ac_09_1"]["verdict"] in {"met", "met_at_point_estimate_only"}


def test_corpus_checks_after_enrich(setup, eval_settings, registry, embedder):
    assert enrich_versions([], eval_settings, registry).run.failed == 0
    checks = evaluation.run_enrichment_evaluation(setup["manifest"], setup["gold"], eval_settings, registry)["corpus_checks"]
    assert checks["status"] == "checked" and set(checks["enrichment"].values()) == {"current"}
    assert checks["ac_07_2"]["entities"] > 0 and checks["ac_07_2"]["verdict"] == "met"
    assert checks["ac_08_1"]["verdict"] == "met"
    for key in ("ac_07_3", "ac_09_3"):
        assert checks[key]["verdict"] == "met" and all(row["results"] > 0 for row in checks[key]["modes"].values())
    # The private document mentions PostgreSQL and indexes too, but it is outside the evaluation scope.
    private = registry.get_document(setup["private"].document_id).source_key
    assert private not in checks["enrichment"]


# CLI and report

def test_cli_writes_both_reports_and_rejects_a_mode(setup, eval_settings, registry, embedder, monkeypatch, capsys, tmp_path):
    segmentation_gold(setup, eval_settings, registry)
    monkeypatch.setattr("techdocqa.cli.load_settings", lambda *_: eval_settings)
    reports = tmp_path / "reports"
    # Round 2's gold folder has no fixtures of its own, so --fixtures names them.
    fixtures = tmp_path / "fixtures.jsonl"
    fixtures.write_bytes((setup["gold"] / "out_of_topic.jsonl").read_bytes())
    assert main(["eval", "--enrichment", "--manifest", str(setup["manifest"]), "--gold-dir", str(setup["gold"]),
                 "--fixtures", str(fixtures), "--report-dir", str(reports)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["acceptance"]["AC-07.4"] == "awaiting_gold_data" and output["acceptance"]["AC-06.4"] == "too_few_sentences"
    markdown = Path(output["report_files"]["markdown"]).read_text(encoding="utf-8")
    assert "## Acceptance" in markdown and "## Sentence boundaries (AC-06.4, P9-2)" in markdown and "similarity_config_id" in markdown
    stored = json.loads(Path(output["report_files"]["json"]).read_text(encoding="utf-8"))
    assert stored["provenance"]["gold_files"]["segmentation"]["status"] == "frozen"
    assert stored["provenance"]["gold_files"]["entities"]["status"] == "awaiting_gold_data"
    assert stored["provenance"]["out_of_topic"]["sha256"] == hashlib.sha256((setup["gold"] / "out_of_topic.jsonl").read_bytes()).hexdigest()
    assert stored["provenance"]["out_of_topic"]["path"] == fixtures.as_posix()
    assert main(["eval", "--enrichment", "--mode", "bm25"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "INVALID_ARGUMENT"
