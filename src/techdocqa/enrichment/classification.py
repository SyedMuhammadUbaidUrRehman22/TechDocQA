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


def config_id(enrichment, profile: dict | None) -> str:
    values = {"policy": CLASSIFIER_POLICY, "method": enrichment.classification_method,
              "profile_id": profile["profile_id"] if profile else None,
              "categories": [[category.name, category.description] for category in enrichment.categories],
              "max_categories": enrichment.max_categories, "threshold": enrichment.unclassified_threshold,
              "calibration_run_id": enrichment.calibration_run_id}
    return "cc_" + hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def description_key(profile: dict, description: str) -> str:
    return hashlib.sha256(json.dumps([profile["profile_id"], description], separators=(",", ":")).encode()).hexdigest()


def category_vectors(settings, profile: dict, registry) -> dict[str, np.ndarray]:
    """Stored after the first embedding, so a rerun makes no model call."""
    from techdocqa.indexing import embeddings
    vectors, embedder = {}, None
    for category in settings.enrichment.categories:
        key = description_key(profile, category.description)
        blob = registry.category_vector(key)
        if blob is None:
            embedder = embedder or embeddings.build_embeddings(settings)
            vector = embeddings.embed_query(category.description, settings, profile, embedder)
            blob = embeddings.encode_vector(vector)
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


def assign(ranked: list[tuple[str, float]], enrichment) -> tuple[list[dict], str]:
    """The top max_categories with their assignment, and the document's classification status."""
    threshold = enrichment.unclassified_threshold
    top = ranked[:enrichment.max_categories]
    rows = [{"rank": rank, "category": name, "confidence": score,
             "assigned": threshold is not None and score >= threshold} for rank, (name, score) in enumerate(top, 1)]
    if threshold is None:
        return rows, "not_calibrated"
    return rows, "classified" if any(row["assigned"] for row in rows) else "unclassified"
