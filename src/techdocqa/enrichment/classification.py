"""FR-09 embedding-similarity classification (P9-6).

The document vector is the L2-normalized mean of the stored vectors of its current chunk occurrences. Each configured
category description is embedded once with the query prefix. A category's score is the cosine of the two, rounded to
6 places: a similarity, not a probability. Categories rank by score, then name; up to max_categories at or above the
calibrated threshold are assigned, and none means unclassified. The user-supplied technology and category are never read.
"""

import hashlib
import json

import numpy as np

CLASSIFIER_POLICY = "centroid-cosine-v1"
NOT_CALIBRATED = "CLASSIFICATION_NOT_CALIBRATED"
STALE = "CLASSIFICATION_CALIBRATION_STALE"


def digest(values) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def similarity_config_id(enrichment, profile: dict | None) -> str:
    """What fixes a document's category scores: a threshold is valid only on the scale these define (as Q-07 is for
    retrieval). max_categories and the threshold itself are not part of the scale."""
    return "cs_" + digest({"policy": CLASSIFIER_POLICY, "profile_id": profile["profile_id"] if profile else None,
                           "categories": [[category.name, category.description] for category in enrichment.categories]})


def active_threshold(enrichment, profile: dict | None) -> tuple[float | None, str | None]:
    """The configured threshold when it was calibrated on the active scale; otherwise None and the warning to show."""
    if enrichment.unclassified_threshold is None:
        return None, NOT_CALIBRATED
    if enrichment.similarity_config_id != similarity_config_id(enrichment, profile):
        return None, STALE
    return enrichment.unclassified_threshold, None


def config_id(enrichment, profile: dict | None) -> str:
    threshold, _ = active_threshold(enrichment, profile)
    values = {"policy": CLASSIFIER_POLICY, "method": enrichment.classification_method,
              "profile_id": profile["profile_id"] if profile else None,
              "categories": [[category.name, category.description] for category in enrichment.categories],
              "max_categories": enrichment.max_categories, "threshold": threshold,
              "calibration_run_id": enrichment.calibration_run_id if threshold is not None else None}
    return "cc_" + digest(values)


def description_key(profile: dict, description: str) -> str:
    return hashlib.sha256(json.dumps([profile["profile_id"], description], separators=(",", ":")).encode()).hexdigest()


def category_vectors(settings, profile: dict, registry, *, save: bool = True, embedder=None) -> dict[str, np.ndarray]:
    """Stored after the first embedding, so a rerun makes no model call. With save=False (evaluation) a missing vector
    is embedded in memory and the registry is not written."""
    from techdocqa.indexing import embeddings
    vectors = {}
    for category in settings.enrichment.categories:
        key = description_key(profile, category.description)
        blob = registry.category_vector(key)
        if blob is None:
            embedder = embedder or embeddings.build_embeddings(settings)
            vector = embeddings.embed_query(category.description, settings, profile, embedder)
            blob = embeddings.encode_vector(vector)
            if save:
                registry.save_category_vector(key, profile["profile_id"], blob)
        vectors[category.name] = unit(np.frombuffer(blob, dtype=np.float32))
    return vectors


def unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def document_vector(blobs: list[bytes]) -> np.ndarray | None:
    if not blobs:
        return None
    return unit(np.mean([np.frombuffer(blob, dtype=np.float32).astype(np.float64) for blob in blobs], axis=0))


def scores(document: np.ndarray, categories: dict[str, np.ndarray]) -> list[tuple[str, float]]:
    return sorted(((name, round(float(document @ vector), 6)) for name, vector in categories.items()), key=lambda item: (-item[1], item[0]))


def assign(ranked: list[tuple[str, float]], enrichment, threshold: float | None) -> tuple[list[dict], str]:
    """The top max_categories with their assignment, and the document's classification status. threshold is the one
    that applies (active_threshold), so a stale one leaves the document not_calibrated."""
    top = ranked[:enrichment.max_categories]
    rows = [{"rank": rank, "category": name, "confidence": score,
             "assigned": threshold is not None and score >= threshold} for rank, (name, score) in enumerate(top, 1)]
    if threshold is None:
        return rows, "not_calibrated"
    return rows, "classified" if any(row["assigned"] for row in rows) else "unclassified"
