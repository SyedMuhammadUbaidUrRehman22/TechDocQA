"""FR-09 embedding-similarity classification (P9-6) and the category filter (P9-7), offline with the word-hash embedder."""

import numpy as np
import pytest

from techdocqa.enrichment import classification
from techdocqa.enrichment.pipeline import embedding_profile_or_none, enrich_versions, show_enrichment
from techdocqa.indexing.pipeline import index_versions
from techdocqa.settings import CategorySpec, EnrichmentSettings

from test_enrichment import CATEGORIES, GAZETTEER, enrich_settings, enriched  # noqa: F401
from test_indexing import embedder, indexed, ingest, inline_workers, model_settings, query  # noqa: F401

COOKING = "# Lemon cake\n\n" + "Whisk eggs with sugar, fold in flour and bake the cake for forty minutes. " * 12


def settings_with(**changes):
    values = {"gazetteer": str(GAZETTEER), "categories": CATEGORIES, "unclassified_threshold": 0.45,
              "calibration_run_id": "test_calibration", **changes}
    return EnrichmentSettings(**values)


def inferred(registry, version):
    return [(row["category"], row["assigned"]) for row in registry.version_categories(version.version_id)]


# The classifier itself

def test_scores_rank_by_similarity_then_name():
    categories = {"B": np.array([1.0, 0.0]), "A": np.array([1.0, 0.0]), "C": np.array([0.0, 1.0])}
    assert classification.scores(np.array([1.0, 0.0]), categories) == [("A", 1.0), ("B", 1.0), ("C", 0.0)]


def test_assignment_needs_a_calibrated_threshold_and_keeps_at_most_three():
    ranked = [("A", 0.9), ("B", 0.8), ("C", 0.7), ("D", 0.6)]
    rows, status = classification.assign(ranked, EnrichmentSettings())
    assert status == "not_calibrated" and len(rows) == 3 and not any(row["assigned"] for row in rows)
    rows, status = classification.assign(ranked, EnrichmentSettings(unclassified_threshold=0.75, calibration_run_id="r"))
    assert status == "classified" and [row["assigned"] for row in rows] == [True, True, False]
    rows, status = classification.assign(ranked, EnrichmentSettings(unclassified_threshold=0.95, calibration_run_id="r", max_categories=1))
    assert status == "unclassified" and len(rows) == 1


def test_document_vector_is_the_normalized_mean():
    blobs = [np.array([1, 0], dtype=np.float32).tobytes(), np.array([0, 1], dtype=np.float32).tobytes()]
    assert np.allclose(classification.document_vector(blobs), [2 ** -0.5, 2 ** -0.5])
    assert classification.document_vector([]) is None


def test_config_id_follows_descriptions_threshold_and_profile():
    profile = {"profile_id": "p"}
    base = classification.config_id(settings_with(), profile)
    changed = [CategorySpec(name=c.name, description=c.description + " Edited.") for c in CATEGORIES]
    assert classification.config_id(settings_with(categories=changed), profile) != base
    assert classification.config_id(settings_with(unclassified_threshold=0.5), profile) != base
    assert classification.config_id(settings_with(), {"profile_id": "q"}) != base
    assert classification.config_id(settings_with(), profile) == base


@pytest.mark.parametrize("values", [{"unclassified_threshold": 0.5}, {"calibration_run_id": "r"},
                                    {"categories": [CATEGORIES[0], CATEGORIES[0]]},
                                    {"categories": [CategorySpec(name="Unclassified", description="Anything at all here.")]}])
def test_invalid_classifier_settings_are_rejected(values):
    with pytest.raises(ValueError):
        EnrichmentSettings(**values)


# Through enrich and search

def test_documents_get_their_category_and_an_out_of_topic_one_is_unclassified(indexed, enrich_settings, registry, corpus, embedder):
    path = corpus / "cooking.md"
    path.write_text(COOKING, encoding="utf-8")
    cooking = ingest(path, enrich_settings, registry)
    assert index_versions([], enrich_settings, registry).run.failed == 0
    assert enrich_versions([], enrich_settings, registry).run.failed == 0
    assert inferred(registry, indexed["kafka.md"])[0] == ("Distributed streaming", True)
    assert inferred(registry, indexed["redis.md"])[0] == ("Caching", True)
    assert inferred(registry, indexed["http.md"])[0] == ("Web", True)
    # AC-09.2: the cooking article is outside every configured topic.
    assert registry.enrichment_state(cooking.version_id)["classification_status"] == "unclassified"
    assert show_enrichment(cooking.document_id, enrich_settings, registry)["categories"]["effective"] == [
        {"category": "unclassified", "source": "embedding"}]
    found = query(enrich_settings, registry, "eggs sugar", category="unclassified").results
    assert found and {item.document_id for item in found} == {cooking.document_id}


@pytest.mark.parametrize("mode", ["bm25", "vector"])
def test_ac_09_3_a_category_filter_returns_no_other_category(enriched, enrich_settings, registry, mode):
    results = query(enrich_settings, registry, "keys memory brokers streams templates", mode=mode, category="Caching", top_k=20).results
    assert results and {item.document_id for item in results} == {enriched["redis.md"].document_id}
    assert query(enrich_settings, registry, "anything", mode=mode, category="Databases").results == []


def test_a_user_category_takes_precedence(enriched, enrich_settings, registry, corpus, embedder):
    path = corpus / "store.md"
    path.write_text("# Store\n\n" + "Redis keeps keys in memory. The snake_case_setting controls eviction. " * 12, encoding="utf-8")
    store = ingest(path, enrich_settings, registry, category="Databases")
    assert index_versions([], enrich_settings, registry).run.failed == 0
    assert enrich_versions([], enrich_settings, registry).run.failed == 0
    # The classifier still infers Caching, but the user-supplied category decides (FR-09.4).
    assert inferred(registry, store)[0] == ("Caching", True)
    assert store.document_id not in {item.document_id for item in query(enrich_settings, registry, "keys", category="Caching", top_k=20).results}
    assert {item.document_id for item in query(enrich_settings, registry, "keys", category="Databases").results} == {store.document_id}
    assert show_enrichment(store.document_id, enrich_settings, registry)["categories"]["effective"] == [{"category": "Databases", "source": "user"}]


def test_the_classifier_never_reads_user_technology_or_category(indexed, enrich_settings, registry, corpus, embedder):
    # Misleading metadata: the text is about caching, the user says Kafka and Web. The stored scores are exactly the
    # cosines of the chunk-vector centroid against the description vectors, so the metadata played no part.
    path = corpus / "store.md"
    path.write_text("# Store\n\n" + "Redis keeps keys in memory. The snake_case_setting controls eviction. " * 12, encoding="utf-8")
    store = ingest(path, enrich_settings, registry, technology="Kafka", category="Web")
    assert index_versions([], enrich_settings, registry).run.failed == 0
    assert enrich_versions([], enrich_settings, registry).run.failed == 0
    profile = embedding_profile_or_none(enrich_settings)
    record = registry.get_version(store.version_id)
    blobs = registry.chunk_vectors(store.version_id, profile["profile_id"], record.chunking.chunking_config_id)
    expected = classification.scores(classification.document_vector(blobs),
                                     classification.category_vectors(enrich_settings, profile, registry))
    stored = [(row["category"], row["confidence"]) for row in registry.version_categories(store.version_id)]
    assert stored == expected[:len(stored)] and stored[0][0] == "Caching"


def test_category_vectors_are_embedded_once(indexed, enrich_settings, registry, embedder):
    assert enrich_versions([], enrich_settings, registry).run.failed == 0
    calls = embedder.queries
    assert calls == len(CATEGORIES)
    # A new threshold recomputes every document but reuses the stored description vectors.
    enrich_settings.enrichment = settings_with(unclassified_threshold=0.5)
    assert enrich_versions([], enrich_settings, registry).run.processed == len(indexed)
    assert embedder.queries == calls


def test_rows_from_another_classifier_never_filter(enriched, enrich_settings, registry):
    assert query(enrich_settings, registry, "keys", category="Caching").results
    enrich_settings.enrichment = settings_with(unclassified_threshold=0.5)
    assert query(enrich_settings, registry, "keys", category="Caching").results == []
    assert show_enrichment(enriched["redis.md"].document_id, enrich_settings, registry)["status"] == "stale"


def test_without_vectors_or_a_threshold_classification_is_reported(corpus, enrich_settings, registry, embedder):
    path = corpus / "kafka.md"
    path.write_text("# Kafka guide\n\n" + "Kafka brokers replicate partitions. " * 12, encoding="utf-8")
    version = ingest(path, enrich_settings, registry, technology="Kafka")
    result = enrich_versions([], enrich_settings, registry)
    assert "CLASSIFICATION_NOT_EMBEDDED" in result.warnings
    assert registry.enrichment_state(version.version_id)["classification_status"] == "not_embedded"
    assert index_versions([], enrich_settings, registry).run.failed == 0
    enrich_settings.enrichment = settings_with(unclassified_threshold=None, calibration_run_id=None)
    result = enrich_versions([], enrich_settings, registry)
    assert "CLASSIFICATION_NOT_CALIBRATED" in result.warnings
    assert registry.enrichment_state(version.version_id)["classification_status"] == "not_calibrated"
    # Uncalibrated scores are stored but assign nothing, so no inferred category filters.
    assert registry.version_categories(version.version_id) and query(enrich_settings, registry, "brokers", category="Distributed streaming").results == []


def test_a_partially_embedded_version_is_not_classified(corpus, enrich_settings, registry, embedder):
    # An index run interrupted between batches leaves some chunks with no chunk_embeddings row at all.
    path = corpus / "store.md"
    path.write_text("# Store\n\n" + "Redis keeps keys in memory. The snake_case_setting controls eviction. " * 40, encoding="utf-8")
    store = ingest(path, enrich_settings, registry, technology="Redis")
    assert index_versions([], enrich_settings, registry).run.failed == 0
    profile = embedding_profile_or_none(enrich_settings)
    record = registry.get_version(store.version_id)
    assert record.chunking.chunk_count > 1
    assert registry.chunk_vectors(store.version_id, profile["profile_id"], record.chunking.chunking_config_id) is not None
    first = registry.execute("SELECT MIN(chunk_id) FROM chunk_embeddings WHERE version_id=?", (store.version_id,)).fetchone()[0]
    registry.execute("DELETE FROM chunk_embeddings WHERE version_id=? AND chunk_id=?", (store.version_id, first))
    assert registry.chunk_vectors(store.version_id, profile["profile_id"], record.chunking.chunking_config_id) is None
    assert enrich_versions([], enrich_settings, registry).run.failed == 0
    assert registry.enrichment_state(store.version_id)["classification_status"] == "not_embedded"
