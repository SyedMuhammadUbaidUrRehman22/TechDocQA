"""Explicit enrich runs over active chunked versions (FR-07 to FR-09, P9-8).

Each document is computed first and written in one transaction. Rows carry the chunk identity and configuration they
came from, so an unchanged document is skipped and a re-chunked or reconfigured one is recomputed.
"""

import hashlib
import json
import time

from techdocqa.enrichment import classification, entities, keyphrases
from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.chunks import active_chunks, verify_chunking
from techdocqa.ingestion.processing import finalized_documents
from techdocqa.schemas import BatchResult


class EnrichmentBatchResult(BatchResult):
    enrichment_config_id: str
    entities: int = 0
    verified_entities: int = 0
    keyphrases: int = 0
    classified: int = 0
    durations_ms: dict[str, int] = {}
    warnings: list[str] = []


def embedding_profile_or_none(settings):
    from techdocqa.indexing.embeddings import embedding_profile
    try:
        return embedding_profile(settings.model)
    except TechDocQAError:
        return None


def configuration(settings) -> dict:
    """Every identity a row records; a change to any of them makes existing rows stale."""
    enrichment = settings.enrichment
    gazetteer = entities.Gazetteer(enrichment.gazetteer)
    profile = embedding_profile_or_none(settings)
    ids = {"entity_config_id": entities.config_id(gazetteer, enrichment.entity_verification_threshold),
           "keyphrase_config_id": keyphrases.config_id(enrichment),
           "classifier_config_id": classification.config_id(enrichment, profile)}
    ids["enrichment_config_id"] = "en_" + hashlib.sha256(json.dumps(ids, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"gazetteer": gazetteer, "profile": profile, "ids": ids, "keyphrases_available": keyphrases.rake_version() is not None}


def entity_rows(chunks, documents, gazetteer, technology, threshold) -> tuple[list[dict], set]:
    context = entities.context_keys([chunk["text"] for chunk in chunks], gazetteer, technology)
    rows, verified = [], set()
    for chunk in chunks:
        page = documents[chunk["document_index"]].page_content
        for mention in entities.extract(chunk["text"], gazetteer, context):
            start, end = chunk["start"] + mention.start, chunk["start"] + mention.end
            # Write-time provenance check (P9-4): both offsets must slice back to the stored text.
            if chunk["text"][mention.start:mention.end] != mention.text or page[start:end] != mention.text:
                raise TechDocQAError("ENTITY_OFFSET_MISMATCH", "An entity offset does not match its source text.", stage="enrichment")
            is_verified = mention.confidence >= threshold
            rows.append({"chunk_id": chunk["chunk_id"], "text": mention.text, "canonical": mention.canonical,
                         "entity_key": mention.key, "type": mention.type, "source": "rule", "rule_id": mention.rule_id,
                         "confidence": mention.confidence, "verified": is_verified, "chunk_start": mention.start,
                         "chunk_end": mention.end, "document_index": chunk["document_index"], "document_start": start,
                         "document_end": end})
            if is_verified:
                verified.add((chunk["chunk_id"], mention.key))
    return rows, verified


def keyphrase_rows(chunks, documents, sentence_spans, enrichment) -> list[tuple]:
    rows = [("document", rank, phrase, score) for rank, (phrase, score) in enumerate(keyphrases.ranked(
        keyphrases.document_sentences(documents, sentence_spans, enrichment.keyphrases_include_code), enrichment,
        enrichment.keyphrases_per_document), 1)]
    if enrichment.keyphrases_per_chunk:
        for chunk in chunks:
            found = keyphrases.ranked(keyphrases.chunk_sentences(chunk, documents, sentence_spans, enrichment.keyphrases_include_code),
                                      enrichment, enrichment.keyphrases_per_document)
            rows += [(chunk["chunk_id"], rank, phrase, score) for rank, (phrase, score) in enumerate(found, 1)]
    return rows


class Categories:
    """Category description vectors, embedded at most once per run and then read from the registry."""

    def __init__(self, settings, profile, registry):
        self.settings, self.profile, self.registry, self.vectors = settings, profile, registry, None

    def classify(self, record) -> tuple[list[dict], str]:
        enrichment = self.settings.enrichment
        if not enrichment.categories:
            return [], "not_configured"
        if self.profile is None:
            return [], "not_embedded"
        blobs = self.registry.chunk_vectors(record.version_id, self.profile["profile_id"], record.chunking.chunking_config_id)
        if blobs is None:
            return [], "not_embedded"
        if self.vectors is None:
            self.registry.save_embedding_profile(self.profile)
            self.vectors = classification.category_vectors(self.settings, self.profile, self.registry)
        ranked = classification.scores(classification.document_vector(blobs), self.vectors)
        return classification.assign(ranked, enrichment)


def enrich_version(record, settings, registry, config, categories) -> dict:
    enrichment = settings.enrichment
    data = verify_chunking(record, settings, registry)
    chunks = data["chunks"]
    documents = finalized_documents(record.version_id, settings, registry)
    rows, verified = entity_rows(chunks, documents, config["gazetteer"], record.technology, enrichment.entity_verification_threshold)
    phrases = keyphrase_rows(chunks, documents, data["sentence_spans"], enrichment) if config["keyphrases_available"] else []
    category_rows, status = categories.classify(record)
    state = {**config["ids"], "chunking_config_id": record.chunking.chunking_config_id, "snapshot_hash": record.chunking.snapshot_hash,
             "keyphrase_status": "extracted" if config["keyphrases_available"] else "unavailable", "classification_status": status}
    return {"state": state, "entities": rows, "verified": verified, "keyphrases": phrases, "categories": category_rows}


def enrich_versions(version_ids: list[str], settings, registry) -> EnrichmentBatchResult:
    config = configuration(settings)
    profile = config["profile"]
    with registry.registration_lock():
        registry.recover_interrupted_runs()
        version_ids = version_ids or [record.version_id for record in registry.eligible_versions()]
        if not version_ids:
            raise TechDocQAError("NO_ELIGIBLE_VERSIONS", "No active chunked versions are available.", stage="enrichment")
        run_id, attempts = registry.start_run(len(version_ids), stage="enrichment")
        categories = Categories(settings, profile, registry)
        totals = {"entities": 0, "verified_entities": 0, "keyphrases": 0, "classified": 0}
        durations, statuses = {}, set()
        for version_id, attempt_id in zip(version_ids, attempts, strict=True):
            started = time.perf_counter()
            try:
                record = registry.begin_enrichment(version_id, attempt_id)
                current = registry.enrichment_state(version_id)
                if current and all(current[key] == value for key, value in (
                        ("chunking_config_id", record.chunking.chunking_config_id), ("snapshot_hash", record.chunking.snapshot_hash),
                        ("enrichment_config_id", config["ids"]["enrichment_config_id"]))):
                    registry.save_enrichment(version_id, attempt_id, current, skipped=True)
                    statuses.add(current["classification_status"])
                else:
                    found = enrich_version(record, settings, registry, config, categories)
                    registry.save_enrichment(version_id, attempt_id, found["state"], entities=found["entities"], verified=found["verified"],
                                             keyphrases=found["keyphrases"], categories=found["categories"])
                    statuses.add(found["state"]["classification_status"])
                state = registry.enrichment_state(version_id)
                totals["entities"] += state["entity_count"]
                totals["verified_entities"] += state["verified_count"]
                totals["keyphrases"] += sum(len(items) for items in registry.version_keyphrases(version_id).values())
                totals["classified"] += state["classification_status"] == "classified"
            except TechDocQAError as error:
                registry.fail_attempt(attempt_id, error.response.error)
            except (OSError, ValueError, TypeError, KeyError, IndexError):
                registry.fail_attempt(attempt_id, TechDocQAError("ENRICHMENT_FAILED", "Enrichment failed safely.", stage="enrichment").response.error)
            durations[version_id] = round((time.perf_counter() - started) * 1000)
        registry.finish_run(run_id)
        warnings = []
        if not config["keyphrases_available"]:
            warnings.append("KEYPHRASES_UNAVAILABLE")
        warnings += sorted({"not_calibrated": "CLASSIFICATION_NOT_CALIBRATED", "not_embedded": "CLASSIFICATION_NOT_EMBEDDED",
                            "not_configured": "CLASSIFICATION_NOT_CONFIGURED"}[status] for status in statuses
                           if status in {"not_calibrated", "not_embedded", "not_configured"})
        return EnrichmentBatchResult(**registry.get_run(run_id).model_dump(), enrichment_config_id=config["ids"]["enrichment_config_id"],
                                     durations_ms=durations, warnings=warnings, **totals)


def show_enrichment(document_id: str, settings, registry, chunk_id: str | None = None) -> dict:
    """Read-only (FR-07.4, FR-08.4): the active version's entities, keyphrases and categories, and whether they are current."""
    version_id = registry.active_version(document_id)
    if version_id is None:
        raise TechDocQAError("NO_ACTIVE_VERSION", "This document has no active version.", stage="enrichment", document_id=document_id)
    record = registry.get_version(version_id)
    state = registry.enrichment_state(version_id)
    config = configuration(settings)
    current = bool(state and record.chunking and state["snapshot_hash"] == record.chunking.snapshot_hash
                   and state["enrichment_config_id"] == config["ids"]["enrichment_config_id"])
    if chunk_id is not None and chunk_id not in {chunk["chunk_id"] for chunk in active_chunks(version_id, settings, registry)}:
        raise TechDocQAError("NOT_FOUND", "The chunk is not a current chunk of this document.", stage="enrichment", document_id=document_id)
    phrases = registry.version_keyphrases(version_id)
    inferred = registry.version_categories(version_id)
    effective = ([{"category": record.category, "source": "user"}] if record.category else
                 [{"category": row["category"], "source": "embedding"} for row in inferred if row["assigned"]]
                 or ([{"category": "unclassified", "source": "embedding"}] if state and state["classification_status"] == "unclassified" else []))
    return {"document_id": document_id, "version_id": version_id, "status": "current" if current else ("stale" if state else "not_enriched"),
            "enrichment": state, "categories": {"effective": effective, "inferred": inferred},
            "keyphrases": phrases.get(chunk_id or "document", []), "entities": registry.version_entities(version_id, chunk_id)}
