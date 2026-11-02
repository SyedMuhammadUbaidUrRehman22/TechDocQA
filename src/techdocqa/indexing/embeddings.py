"""Embedding profile identity, provider construction and vector validation (FR-11)."""

import hashlib
import json
from math import isfinite

import numpy as np

from techdocqa.errors import TechDocQAError
from techdocqa.settings import ModelSettings, Settings

SCORE_POLICY = "cosine-distance-half-v1"
METRIC = "cosine"
NORM_TOLERANCE = 1e-3


def embedding_profile(model: ModelSettings) -> dict:
    if not (model.embedding_model and model.embedding_dimension):
        raise TechDocQAError("EMBEDDING_PROFILE_UNVERIFIED", "Select an embedding model and its verified dimension.", stage="configuration")
    model_id = f"{model.provider}/{model.embedding_model}@{model.embedding_model_digest}"
    values = {"provider": model.provider, "embedding_model_id": model_id, "dimension": model.embedding_dimension,
              "normalization": model.embedding_normalization, "metric": METRIC,
              "document_prefix": model.embedding_prefix, "query_prefix": model.embedding_query_prefix}
    profile_id = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # One collection per profile: different models or dimensions never share an index.
    return {**values, "profile_id": profile_id, "collection": f"emb_{profile_id[:32]}"}


def chunk_key(text_hash: str, chunking_config_id: str, embedding_model_id: str) -> str:
    return hashlib.sha256(json.dumps([text_hash, chunking_config_id, embedding_model_id], separators=(",", ":")).encode()).hexdigest()


def invalid_reason(vector, profile: dict) -> str | None:
    """Reason a provider vector cannot be stored, or None when it is valid."""
    if len(vector) != profile["dimension"]:
        return "INVALID_DIMENSION"
    if not all(isfinite(value) for value in vector):
        return "NON_FINITE_VALUE"
    norm = float(np.linalg.norm(np.asarray(vector, dtype=np.float64)))
    if norm == 0:
        return "ZERO_NORM"
    if profile["normalization"] == "l2" and abs(norm - 1) > NORM_TOLERANCE:
        return "NOT_NORMALIZED"
    return None


def encode_vector(vector) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def decode_vector(blob: bytes) -> list[float]:
    return np.frombuffer(blob, dtype=np.float32).tolist()


def build_embeddings(settings: Settings):
    """Construct the configured framework embedder after confirming the pinned model is what is installed."""
    model = settings.model
    if model.provider != "ollama":
        raise TechDocQAError("PROVIDER_NOT_AVAILABLE", "Only the local Ollama embedding provider is installed.", stage="embedding")
    import ollama
    from langchain_ollama import OllamaEmbeddings
    client_kwargs = {"timeout": model.timeout_seconds}
    try:
        installed = {item.model: item.digest for item in ollama.Client(host=model.base_url, **client_kwargs).list().models}
    except Exception:
        raise TechDocQAError("EMBEDDING_PROVIDER_UNAVAILABLE", "The embedding provider is unreachable.", stage="embedding", retryable=True) from None
    if installed.get(model.embedding_model) != model.embedding_model_digest:
        raise TechDocQAError("EMBEDDING_MODEL_CHANGED", "The installed embedding model does not match the pinned digest.", stage="embedding")
    return OllamaEmbeddings(model=model.embedding_model, base_url=model.base_url, client_kwargs=client_kwargs)


def embed_query(query: str, settings: Settings, profile: dict, embedder=None) -> list[float]:
    embedder = embedder or build_embeddings(settings)
    try:
        vector = embedder.embed_query(settings.model.embedding_query_prefix + query)
    except Exception:
        raise TechDocQAError("EMBEDDING_PROVIDER_UNAVAILABLE", "The query could not be embedded.", stage="embedding", retryable=True) from None
    if invalid_reason(vector, profile):
        raise TechDocQAError("INVALID_EMBEDDING", "The provider returned an invalid query vector.", stage="embedding")
    return vector
