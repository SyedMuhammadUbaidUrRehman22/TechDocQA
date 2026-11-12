"""eval --enrichment: Phase 9 measurement (P9-9, plan step 8). Read-only: no registry, index or configuration write.

Scores AC-06.4 (both segmentation policies), AC-07.4, AC-08.3 and AC-09.1 against the frozen gold sets and manifest
labels, classifies the out-of-topic fixtures in memory for AC-09.2, proposes the `unclassified` threshold, and checks
AC-07.2, AC-07.3, AC-08.1 and AC-09.3 on the enriched corpus. A gold set that is not frozen yet is reported as awaiting
data, never guessed. Every rate carries its denominator and a Wilson 95% interval; a target met only at the point
estimate is reported that way (VULN-04). DDIA and every other document outside the manifest's evaluation scope are
never read.
"""

from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from math import sqrt
from pathlib import Path
import statistics
import time
import unicodedata
import uuid

from techdocqa.errors import TechDocQAError

GOLD_FILES = {"segmentation": "segmentation_gold.jsonl", "entities": "entities_gold.jsonl", "keyphrases": "keyphrases_gold.jsonl"}
OUT_OF_TOPIC = "out_of_topic.jsonl"
TARGETS = {"AC-06.4": {"boundary_f1": 0.95, "min_sentences": 50},
           "AC-07.4": {"precision": 0.80, "recall": 0.60, "min_chunks": 20},
           "AC-08.3": {"mean_hit_rate": 0.50, "documents": 5, "top": 10},
           "AC-09.1": {"accuracy": 0.85, "min_documents_per_category": 2}}
TOP_TERMS = 10
CONTEXT = 25
DIGITS = 6
Z = 1.959964


def normalized(text: str) -> str:
    """The gold comparison form: NFKC, case-folded, whitespace collapsed (GUIDELINES, Q-16)."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def wilson(successes: int, total: int) -> dict | None:
    """Wilson score interval at 95%; None without observations."""
    if total <= 0:
        return None
    p = successes / total
    centre = (p + Z * Z / (2 * total)) / (1 + Z * Z / total)
    half = Z * sqrt(p * (1 - p) / total + Z * Z / (4 * total * total)) / (1 + Z * Z / total)
    return {"low": round(max(0.0, centre - half), 4), "high": round(min(1.0, centre + half), 4)}


def rate(successes: int, total: int) -> dict:
    return {"value": round(successes / total, DIGITS) if total else None, "numerator": successes, "denominator": total,
            "interval": wilson(successes, total)}


def f1(precision: float | None, recall: float | None) -> float | None:
    if not precision or not recall:
        return 0.0 if precision is not None and recall is not None else None
    return round(2 * precision * recall / (precision + recall), DIGITS)


def verdict(point: float | None, low: float | None, target: float) -> str:
    if point is None:
        return "not_measured"
    if low is not None and low >= target:
        return "met"
    return "met_at_point_estimate_only" if point >= target else "not_met"


def snippet(text: str, position: int) -> str:
    """A short excerpt around a position, whitespace collapsed, with the position marked."""
    left = " ".join(text[max(0, position - CONTEXT):position].split())
    right = " ".join(text[position:position + CONTEXT].split())
    return f"{left}|{right}"


def read_jsonl(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        raise TechDocQAError("GOLD_NOT_READABLE", "A gold or fixture file is unreadable.", stage="evaluation") from None


class Scope:
    """The manifest's evaluation documents that are eligible now, loaded lazily and verified once."""

    def __init__(self, manifest: dict, settings, registry):
        self.manifest, self.settings, self.registry = manifest, settings, registry
        eligible = {record.source_key: record for record in registry.eligible_versions()}
        self.records = {key: eligible[key] for key in sorted(manifest["documents"]) if key in eligible}
        self.missing = sorted(set(manifest["documents"]) - set(self.records))
        self.loaded = {}

    def load(self, key: str) -> dict:
        if key not in self.loaded:
            from techdocqa.ingestion.chunks import verify_chunking
            from techdocqa.ingestion.processing import finalized_documents
            record = self.records[key]
            self.loaded[key] = {"record": record, "documents": finalized_documents(record.version_id, self.settings, self.registry),
                                "data": verify_chunking(record, self.settings, self.registry)}
        return self.loaded[key]

    def span(self, item: dict) -> str | None:
        """The gold span's current text, or None when its source left the scope or its text changed."""
        if item["source_key"] not in self.records:
            return None
        documents = self.load(item["source_key"])["documents"]
        if not 0 <= item["document_index"] < len(documents):
            return None
        text = documents[item["document_index"]].page_content[item["start"]:item["end"]]
        return text if hashlib.sha256(text.encode("utf-8")).hexdigest() == item["text_sha256"] else None

    def format(self, key: str) -> str | None:
        return self.manifest["documents"][key].get("format")


def gold_sets(directory: Path) -> dict:
    found = {}
    for name, filename in GOLD_FILES.items():
        path = Path(directory) / filename
        found[name] = ({"status": "frozen", "path": path.as_posix(), "sha256": sha256_file(path), "rows": read_jsonl(path)}
                       if path.exists() else {"status": "awaiting_gold_data", "path": path.as_posix()})
    return found


def grouped(rows: list[dict], key: str, fields: tuple[str, ...]) -> dict:
    groups = {}
    for row in rows:
        bucket = groups.setdefault(str(row[key]), dict.fromkeys(fields, 0))
        for field in fields:
            bucket[field] += row[field]
    return dict(sorted(groups.items()))


# AC-06.4: sentence boundaries

def segmentation_policy_scores(name: str, rows: list[dict], scope: Scope) -> dict:
    from techdocqa.segmentation import POLICIES, segmenter
    split = segmenter(name)
    cache, per_passage, errors, exact = {}, [], [], 0
    started = time.perf_counter()
    for row in rows:
        document = scope.load(row["source_key"])["documents"][row["document_index"]]
        page = document.page_content
        key = (row["source_key"], row["document_index"])
        if key not in cache:
            cache[key] = split(page, document.metadata.get("code_spans"))
        start, gold = row["start"], row["sentences"]
        first, last = start + gold[0][0], start + gold[-1][1]
        expected = {start + end for _, end in gold[:-1]}
        predicted = set()
        for span in cache[key]:
            piece = page[span["start"]:span["end"]]
            if not piece.strip() or span["end"] <= first or span["start"] >= last:
                continue
            end = span["start"] + len(piece.rstrip())
            if first < end < last:
                predicted.add(end)
        for index, (begin, end) in enumerate(gold):
            left = index == 0 or start + gold[index - 1][1] in predicted
            right = index == len(gold) - 1 or start + end in predicted
            exact += left and right and not any(start + begin < point < start + end for point in predicted)
        errors += [{"passage": row["id"], "kind": kind, "offset": point - start, "context": snippet(page, point)}
                   for kind, points in (("missed", expected - predicted), ("spurious", predicted - expected)) for point in sorted(points)]
        per_passage.append({"id": row["id"], "technology": row["technology"], "format": row["format"], "gold": len(expected),
                            "predicted": len(predicted), "matched": len(expected & predicted)})
    matched = sum(row["matched"] for row in per_passage)
    gold_total = sum(row["gold"] for row in per_passage)
    predicted_total = sum(row["predicted"] for row in per_passage)
    precision, recall = rate(matched, predicted_total), rate(matched, gold_total)
    sentences = sum(len(row["sentences"]) for row in rows)
    low = f1((precision["interval"] or {}).get("low"), (recall["interval"] or {}).get("low"))
    value = f1(precision["value"], recall["value"])
    split_by = lambda field: {group: {**counts, "f1": f1(counts["matched"] / counts["predicted"] if counts["predicted"] else None,
                                                      counts["matched"] / counts["gold"] if counts["gold"] else None)}
                              for group, counts in grouped(per_passage, field, ("gold", "predicted", "matched")).items()}
    return {"policy": POLICIES[name], "boundary_f1": value, "boundary_f1_from_lower_bounds": low, "precision": precision,
            "recall": recall, "sentences": sentences, "exact_sentences": rate(exact, sentences),
            "verdict": verdict(value, low, TARGETS["AC-06.4"]["boundary_f1"]) if sentences >= TARGETS["AC-06.4"]["min_sentences"]
            else "too_few_sentences", "by_technology": split_by("technology"), "by_format": split_by("format"),
            "passages": per_passage, "errors": errors, "duration_ms": round((time.perf_counter() - started) * 1000)}


def score_segmentation(gold: dict, scope: Scope) -> dict:
    from techdocqa.segmentation import spacy_version
    if gold["status"] != "frozen":
        return {"status": gold["status"]}
    rows = [row for row in gold["rows"] if scope.span(row) is not None]
    flagged = [row["id"] for row in gold["rows"] if row not in rows]
    policies = {"rules": segmentation_policy_scores("rules", rows, scope)}
    policies["spacy"] = (segmentation_policy_scores("spacy", rows, scope) if spacy_version()
                         else {"status": "unavailable", "reason": "SEGMENTER_UNAVAILABLE"})
    spacy, rules = policies["spacy"], policies["rules"]
    beats = spacy.get("boundary_f1") is not None and spacy["boundary_f1"] > rules["boundary_f1"]
    return {"status": "scored", "passages": len(rows), "flagged": flagged, "policies": policies,
            # AC-06.4 is the P1 criterion, so it judges the spaCy policy; P9-2 adopts it only if it also beats the rules.
            "ac_06_4": spacy.get("verdict", "not_measured"), "spacy_beats_rules": beats,
            "definition": "Boundary F1 over the boundaries between sentences inside each paragraph: a sentence end and the next "
                          "sentence's start, compared at exact positions after trimming whitespace. Paragraph edges are fixed "
                          "by the fixture, so they are not counted."}


# AC-07.4: entities

def score_entities(gold: dict, scope: Scope, settings) -> dict:
    from techdocqa.enrichment import entities
    if gold["status"] != "frozen":
        return {"status": gold["status"]}
    gazetteer = entities.Gazetteer(settings.enrichment.gazetteer)
    threshold = settings.enrichment.entity_verification_threshold
    sampled = {row.get("gazetteer_sha256") for row in gold["rows"]} - {None}
    rows, flagged, per_chunk, errors = [], [], [], []
    for row in gold["rows"]:
        text = scope.span(row)
        if text is None:
            flagged.append(row["id"])
            continue
        loaded = scope.load(row["source_key"])
        context = entities.context_keys([chunk["text"] for chunk in loaded["data"]["chunks"]], gazetteer, loaded["record"].technology)
        mentions = entities.extract(text, gazetteer, context)
        found = {}
        for mention in mentions:
            found.setdefault((normalized(mention.text), mention.type), mention)
        verified = {key: mention for key, mention in found.items() if mention.confidence >= threshold}
        expected = {(mention["normalized"], mention["type"]) for mention in row["mentions"]}
        rows.append({"row": row, "verified": verified, "all": found, "expected": expected})
        hits = verified.keys() & expected
        per_chunk.append({"id": row["id"], "technology": row["technology"], "format": row["format"],
                          "ambiguous_stratum": row.get("ambiguous_stratum", False), "gold": len(expected),
                          "predicted": len(verified), "matched": len(hits)})
        gold_texts = {text: kind for text, kind in expected}
        errors.append({"chunk": row["id"],
                       "false_positives": [{"text": mention.text, "type": mention.type, "rule": mention.rule_id,
                                            **({"gold_type": gold_texts[key[0]]} if key[0] in gold_texts else {})}
                                           for key, mention in sorted(verified.items()) if key not in expected],
                       "false_negatives": [{"text": text, "type": kind} for text, kind in sorted(expected - verified.keys())]})

    def precision_of(select) -> dict:
        """Precision over the verified mentions that select(key, mention) keeps."""
        hits = made = 0
        for item in rows:
            chosen = {key for key, mention in item["verified"].items() if select(key, mention)}
            hits += len(chosen & item["expected"])
            made += len(chosen)
        return rate(hits, made)

    def recall_of(kind: str | None) -> dict:
        wanted = [{key for key in item["expected"] if kind is None or key[1] == kind} for item in rows]
        return rate(sum(len(keys & item["verified"].keys()) for keys, item in zip(wanted, rows)), sum(len(keys) for keys in wanted))

    precision, recall = precision_of(lambda key, mention: True), recall_of(None)
    expected_total = recall["denominator"]
    by_type = {kind: {"precision": precision_of(lambda key, mention, kind=kind: key[1] == kind), "recall": recall_of(kind)}
               for kind in ("TECHNOLOGY", "COMPONENT", "CONCEPT", "PROTOCOL", "IDENTIFIER")}
    by_rule = {family: {"precision": precision_of(lambda key, mention, gazetteer_rule=gazetteer_rule:
                                                  mention.rule_id.startswith("gazetteer") == gazetteer_rule)}
               for family, gazetteer_rule in (("gazetteer", True), ("pattern", False))}
    texts = [({key[0] for key in item["verified"]}, {key[0] for key in item["expected"]}) for item in rows]
    text_tp = sum(len(found & wanted) for found, wanted in texts)
    all_tp = sum(len(item["all"].keys() & item["expected"]) for item in rows)
    all_predicted = sum(len(item["all"]) for item in rows)
    split_by = lambda field: {group: {**counts, "precision": rate(counts["matched"], counts["predicted"])["value"],
                                      "recall": rate(counts["matched"], counts["gold"])["value"]}
                              for group, counts in grouped(per_chunk, field, ("gold", "predicted", "matched")).items()}
    targets = TARGETS["AC-07.4"]
    judged = [verdict(precision["value"], (precision["interval"] or {}).get("low"), targets["precision"]),
              verdict(recall["value"], (recall["interval"] or {}).get("low"), targets["recall"])]
    order = ("not_measured", "not_met", "met_at_point_estimate_only", "met")
    return {"status": "scored", "chunks": len(rows), "flagged": flagged, "gazetteer_sha256": gazetteer.sha256,
            "tuned": bool(sampled) and sampled != {gazetteer.sha256}, "threshold": threshold,
            "precision": precision, "recall": recall, "f1": f1(precision["value"], recall["value"]),
            "ac_07_4": min(judged, key=order.index) if len(rows) >= targets["min_chunks"] else "too_few_chunks",
            "by_type": by_type, "by_rule": by_rule, "by_technology": split_by("technology"), "by_format": split_by("format"),
            "by_ambiguous_stratum": split_by("ambiguous_stratum"),
            "diagnostics": {"text_only": {"precision": rate(text_tp, sum(len(found) for found, _ in texts))["value"],
                                          "recall": rate(text_tp, sum(len(wanted) for _, wanted in texts))["value"]},
                            "including_unverified": {"precision": rate(all_tp, all_predicted)["value"],
                                                     "recall": rate(all_tp, expected_total)["value"]}},
            "chunks_detail": per_chunk, "errors": [item for item in errors if item["false_positives"] or item["false_negatives"]]}


# AC-08.3: key terms

def score_keyphrases(gold: dict, scope: Scope, settings) -> dict:
    from techdocqa.enrichment import keyphrases
    if gold["status"] != "frozen":
        return {"status": gold["status"]}
    if keyphrases.rake_version() is None:
        return {"status": "unavailable", "reason": "KEYPHRASES_UNAVAILABLE"}
    rows = [row for row in gold["rows"] if row["source_key"] in scope.records]
    flagged = [row["id"] for row in gold["rows"] if row not in rows]
    enrichment = settings.enrichment
    configured = variant_name(enrichment.keyphrase_metric, enrichment.keyphrases_include_code)
    variants = {}
    # P9-5: every RAKE metric with and without code, so both choices are made from the gold set, not guessed.
    for metric in keyphrases.METRICS:
        for include_code in (True, False):
            options = enrichment.model_copy(update={"keyphrase_metric": metric, "keyphrases_include_code": include_code})
            documents = []
            for row in rows:
                loaded = scope.load(row["source_key"])
                sentences = keyphrases.document_sentences(loaded["documents"], loaded["data"]["sentence_spans"], include_code)
                top = [normalized(phrase) for phrase, _ in keyphrases.ranked(sentences, options, TOP_TERMS)]
                hits = [term for term in row["terms"] if term in top]
                lenient = [term for term in row["terms"] if any(term in phrase or phrase in term for phrase in top)]
                documents.append({"id": row["id"], "technology": row["technology"], "format": row["format"], "terms": len(row["terms"]),
                                  "hits": len(hits), "hit_rate": round(len(hits) / len(row["terms"]), DIGITS),
                                  "lenient_hits": len(lenient), "missed": [term for term in row["terms"] if term not in hits], "top": top})
            variants[variant_name(metric, include_code)] = {
                "metric": metric, "include_code": include_code,
                "mean_hit_rate": round(statistics.mean(row["hit_rate"] for row in documents), DIGITS) if documents else None,
                "pooled_terms": rate(sum(row["hits"] for row in documents), sum(row["terms"] for row in documents)),
                "mean_lenient_hit_rate": round(statistics.mean(row["lenient_hits"] / row["terms"] for row in documents), DIGITS) if documents else None,
                "documents": documents}
    active = variants[configured]
    # The configured variant stays unless another one does strictly better on the mean.
    best = max(variants, key=lambda name: ((variants[name]["mean_hit_rate"] or 0), name == configured))
    enough = len(rows) >= TARGETS["AC-08.3"]["documents"]
    return {"status": "scored", "documents": len(rows), "flagged": flagged, "configured": configured,
            "ac_08_3": verdict(active["mean_hit_rate"], (active["pooled_terms"]["interval"] or {}).get("low"),
                               TARGETS["AC-08.3"]["mean_hit_rate"]) if enough else "too_few_documents",
            "best_variant": best, "variants": variants}


def variant_name(metric: str, include_code: bool) -> str:
    return f"{metric}/{'with_code' if include_code else 'without_code'}"


# FR-09: classification, the threshold and AC-09.2

def fixture_vector(text: str, identifier: str, settings, profile: dict, embedder):
    """An out-of-topic fixture through the same normalization, chunking and document prefix as ingestion, in memory."""
    from langchain_core.documents import Document
    from techdocqa.chunking import build_chunks
    from techdocqa.enrichment.classification import unit
    from techdocqa.indexing import embeddings
    from techdocqa.normalization import normalize_documents
    import numpy as np
    documents = normalize_documents([Document(page_content=text, metadata={"doc_type": "md", "version_id": identifier,
                                                                           "document_id": identifier})], minimum=1)
    chunks = build_chunks(documents, settings.chunking, model=settings.model)["chunks"]
    try:
        vectors = embedder.embed_documents([settings.model.embedding_prefix + chunk["text"] for chunk in chunks])
    except Exception:
        raise TechDocQAError("EMBEDDING_PROVIDER_UNAVAILABLE", "A fixture could not be embedded.", stage="evaluation", retryable=True) from None
    if len(vectors) != len(chunks) or any(embeddings.invalid_reason(vector, profile) for vector in vectors):
        raise TechDocQAError("INVALID_EMBEDDING", "The provider returned an invalid fixture vector.", stage="evaluation")
    return unit(np.mean(np.asarray(vectors, dtype=np.float64), axis=0)), len(chunks)


def rule_baseline(scope: Scope, key: str, gazetteer, configured: set[str], threshold: float) -> str:
    """Verified technology entities mapped to their gazetteer category, by mention count then name. Context comes from
    the text alone, never the user technology, so the baseline cannot read the label (P9-6)."""
    from techdocqa.enrichment import entities
    chunks = scope.load(key)["data"]["chunks"]
    context = entities.context_keys([chunk["text"] for chunk in chunks], gazetteer, None)
    counts = {}
    for chunk in chunks:
        for mention in entities.extract(chunk["text"], gazetteer, context):
            entry = gazetteer.by_key.get(mention.key)
            if mention.type == "TECHNOLOGY" and mention.confidence >= threshold and entry and entry.category in configured:
                counts[entry.category] = counts.get(entry.category, 0) + 1
    return min(counts, key=lambda name: (-counts[name], name)) if counts else "unclassified"


def threshold_proposal(in_topic: list[float], out_of_topic: list[float], similarity_id: str) -> dict | None:
    from techdocqa.answering import sufficiency
    threshold = sufficiency.choose(in_topic, out_of_topic)
    if threshold is None:
        return None
    classified, refused = sufficiency.outcome(threshold, in_topic, out_of_topic)
    return {"policy": sufficiency.CALIBRATION_POLICY, "unclassified_threshold": threshold, "similarity_config_id": similarity_id,
            "margin": round(min(abs(score - threshold) for score in [*in_topic, *out_of_topic]), DIGITS),
            "separable": (classified, refused) == (len(in_topic), len(out_of_topic)),
            "in_topic": len(in_topic), "in_topic_classified": classified,
            "calibration_out_of_topic": len(out_of_topic), "calibration_unclassified": refused,
            "leave_one_out_errors": sufficiency.leave_one_out_errors(in_topic, out_of_topic)}


def score_classification(scope: Scope, settings, registry, fixtures_path: Path) -> dict:
    from techdocqa.enrichment import classification, entities
    from techdocqa.enrichment.pipeline import embedding_profile_or_none
    from techdocqa.indexing import embeddings
    enrichment = settings.enrichment
    if not enrichment.categories:
        return {"status": "not_configured"}
    profile = embedding_profile_or_none(settings)
    if profile is None:
        return {"status": "not_embedded", "reason": "EMBEDDING_PROFILE_UNVERIFIED"}
    configured = {category.name for category in enrichment.categories}
    similarity_id = classification.similarity_config_id(enrichment, profile)
    active, warning = classification.active_threshold(enrichment, profile)
    embedder = None
    try:
        if any(registry.category_vector(classification.description_key(profile, c.description)) is None for c in enrichment.categories):
            embedder = embeddings.build_embeddings(settings)
        vectors = classification.category_vectors(settings, profile, registry, save=False, embedder=embedder)
        gazetteer = entities.Gazetteer(enrichment.gazetteer)
        documents = []
        for key, record in scope.records.items():
            blobs = registry.chunk_vectors(record.version_id, profile["profile_id"], record.chunking.chunking_config_id)
            if blobs is None:
                documents.append({"source_key": key, "format": scope.format(key), "label": record.category, "status": "not_embedded"})
                continue
            ranked = classification.scores(classification.document_vector(blobs), vectors)
            documents.append({"source_key": key, "format": scope.format(key), "label": record.category, "status": "scored",
                              "ranked": ranked[:enrichment.max_categories], "predicted": ranked[0][0], "top_score": ranked[0][1],
                              "rule_baseline": rule_baseline(scope, key, gazetteer, configured,
                                                             enrichment.entity_verification_threshold)})
        fixtures = []
        rows = read_jsonl(fixtures_path)
        if rows:
            embedder = embedder or embeddings.build_embeddings(settings)
        for row in rows:
            vector, chunk_count = fixture_vector(row["text"], f"fixture_{row['id']}", settings, profile, embedder)
            ranked = classification.scores(vector, vectors)
            fixtures.append({"id": row["id"], "split": row["split"], "topic": row["topic"], "chunks": chunk_count,
                             "ranked": ranked[:enrichment.max_categories], "top_score": ranked[0][1]})
    except TechDocQAError as error:
        return {"status": "failed", "error": {"code": error.response.error.code, "message": error.response.error.message}}
    scored = [row for row in documents if row["status"] == "scored"]
    labeled = [row for row in scored if row["label"] in configured]
    in_topic = [row["top_score"] for row in scored]
    calibration = [row["top_score"] for row in fixtures if row["split"] == "calibration"]
    proposal = threshold_proposal(in_topic, calibration, similarity_id) if in_topic and calibration else None
    applied = active if active is not None else (proposal or {}).get("unclassified_threshold")

    def assigned(row, threshold):
        return [name for name, score in row["ranked"] if threshold is not None and score >= threshold]

    correct = sum(row["predicted"] == row["label"] for row in labeled)
    after = sum(applied is not None and row["top_score"] >= applied and row["predicted"] == row["label"] for row in labeled)
    baseline = sum(row["rule_baseline"] == row["label"] for row in labeled)
    names = sorted(configured)
    matrix = {label: {name: sum(1 for row in labeled if row["label"] == label and row["predicted"] == name) for name in names}
              for label in names}
    per_category = {name: sum(1 for row in labeled if row["label"] == name) for name in names}
    top1 = rate(correct, len(labeled))
    strict = rate(after, len(labeled))
    enough = all(count >= TARGETS["AC-09.1"]["min_documents_per_category"] for count in per_category.values())
    held_out = [row for row in fixtures if row["split"] == "held_out"]
    for row in fixtures:
        row["unclassified_under_proposal"] = proposal is not None and row["top_score"] < proposal["unclassified_threshold"]
        row["unclassified_under_active"] = active is not None and row["top_score"] < active
    cooking = [row for row in held_out if row["topic"] == "cooking"]
    judge_with = "active" if active is not None else "proposal"
    for row in scored:
        row["assigned_under_proposal"] = assigned(row, (proposal or {}).get("unclassified_threshold"))
        row["assigned_under_active"] = assigned(row, active)
    return {
        "status": "scored", "similarity_policy": classification.CLASSIFIER_POLICY, "similarity_config_id": similarity_id,
        "classifier_config_id": classification.config_id(enrichment, profile),
        "active_threshold": {"status": "calibrated" if active is not None else ("stale" if warning == classification.STALE else "not_calibrated"),
                             "unclassified_threshold": active, "calibration_run_id": enrichment.calibration_run_id if active is not None else None},
        "documents": documents, "fixtures": fixtures, "proposal": proposal,
        "ac_09_1": {"top1_accuracy": top1, "accuracy_with_threshold": strict, "threshold_used": applied, "threshold_source": judge_with,
                    "rule_baseline_accuracy": rate(baseline, len(labeled)), "documents_per_category": per_category,
                    "confusion_matrix": matrix,
                    # FR-09.2 keeps up to max_categories at or above the threshold; how many each document gets.
                    "assigned_per_document": {str(count): sum(1 for row in scored if len(assigned(row, applied)) == count)
                                              for count in range(enrichment.max_categories + 1)},
                    "verdict": verdict(strict["value"], (strict["interval"] or {}).get("low"), TARGETS["AC-09.1"]["accuracy"])
                    if enough and applied is not None else ("too_few_documents" if not enough else "not_calibrated"),
                    "errors": [{"source_key": row["source_key"], "label": row["label"], "ranked": row["ranked"]} for row in labeled
                               if row["predicted"] != row["label"] or (applied is not None and row["top_score"] < applied)]},
        "ac_09_2": {"threshold_source": judge_with,
                    "held_out_unclassified": rate(sum(row[f"unclassified_under_{judge_with}"] for row in held_out), len(held_out)),
                    "cooking_unclassified": bool(cooking) and all(row[f"unclassified_under_{judge_with}"] for row in cooking),
                    "verdict": ("met" if cooking and all(row[f"unclassified_under_{judge_with}"] for row in cooking) else "not_met")
                    if applied is not None and cooking else "not_measured"},
    }


# Real-corpus checks after enrich: AC-07.2, AC-07.3, AC-08.1, AC-09.3

def corpus_checks(scope: Scope, settings, registry, config: dict) -> dict:
    from techdocqa.retrieval.search import search
    from techdocqa.schemas import SearchFilters, SearchRequest
    states = {}
    for key, record in scope.records.items():
        state = registry.enrichment_state(record.version_id)
        current = bool(state and state["snapshot_hash"] == record.chunking.snapshot_hash
                       and state["enrichment_config_id"] == config["ids"]["enrichment_config_id"])
        states[key] = "current" if current else ("stale" if state else "not_enriched")
    if not states or set(states.values()) != {"current"}:
        return {"status": "not_run", "reason": "ENRICHMENT_NOT_CURRENT", "enrichment": states}
    checks = {"enrichment": states}
    rows = failures = 0
    for key, record in scope.records.items():
        loaded = scope.load(key)
        chunks = {chunk["chunk_id"]: chunk for chunk in loaded["data"]["chunks"]}
        for row in registry.execute("SELECT * FROM entities WHERE version_id=?", (record.version_id,)).fetchall():
            rows += 1
            chunk = chunks.get(row["chunk_id"])
            page = loaded["documents"][row["document_index"]].page_content if row["document_index"] < len(loaded["documents"]) else ""
            failures += not (chunk and row["document_id"] == record.document_id
                             and chunk["text"][row["chunk_start"]:row["chunk_end"]] == row["text"]
                             and page[row["document_start"]:row["document_end"]] == row["text"])
    checks["ac_07_2"] = {"entities": rows, "invalid": failures, "verdict": "met" if rows and not failures else "not_met"}
    sources = frozenset(scope.records)
    verified = registry.entity_chunks("postgresql", config["ids"]["entity_config_id"])
    inferred = registry.inferred_categories(config["ids"]["classifier_config_id"])

    def in_databases(result) -> bool:
        """The effective category, as the filter decides it: the user category, else the current inferred ones (P9-7)."""
        category = registry.get_version(result.version_id).category
        return category.casefold() == "databases" if category else "databases" in inferred.get(result.version_id, set())

    for criterion, filters, accept in (
            ("ac_07_3", SearchFilters(entity="PostgreSQL"), lambda result: result.chunk_id in verified),
            ("ac_09_3", SearchFilters(category="Databases"), in_databases)):
        modes = {}
        for mode in ("bm25", "vector"):
            try:
                response = search(SearchRequest(query="transaction isolation and indexes", mode=mode, top_k=20, filters=filters),
                                  settings, registry, source_keys=sources)
            except TechDocQAError as error:
                modes[mode] = {"status": "failed", "error": error.response.error.code}
                continue
            bad = [result.chunk_id for result in response.results if not accept(result)]
            modes[mode] = {"results": len(response.results), "outside": len(bad),
                           "verdict": "met" if response.results and not bad else "not_met"}
        checks[criterion] = {"filter": filters.model_dump(exclude_none=True), "modes": modes,
                             "verdict": "met" if all(row.get("verdict") == "met" for row in modes.values()) else "not_met"}
    limit, bad = settings.enrichment.keyphrases_per_document, []
    for key, record in scope.records.items():
        phrases = registry.version_keyphrases(record.version_id).get("document", [])
        scores = [row["score"] for row in phrases]
        if not 1 <= len(phrases) <= limit or [row["rank"] for row in phrases] != list(range(1, len(phrases) + 1)) \
                or scores != sorted(scores, reverse=True):
            bad.append(key)
    checks["ac_08_1"] = {"documents": len(scope.records), "invalid": bad, "verdict": "met" if not bad else "not_met"}
    return {"status": "checked", **checks}


def enrichment_times(scope: Scope, settings) -> list[dict]:
    """Per-document in-memory extraction time (P9-12): every chunk's entities and the document's keyphrases."""
    from techdocqa.enrichment import entities, keyphrases
    gazetteer = entities.Gazetteer(settings.enrichment.gazetteer)
    available = keyphrases.rake_version() is not None
    rows = []
    for key in scope.records:
        loaded = scope.load(key)
        chunks = loaded["data"]["chunks"]
        started = time.perf_counter()
        context = entities.context_keys([chunk["text"] for chunk in chunks], gazetteer, loaded["record"].technology)
        found = sum(len(entities.extract(chunk["text"], gazetteer, context)) for chunk in chunks)
        middle = time.perf_counter()
        if available:
            keyphrases.ranked(keyphrases.document_sentences(loaded["documents"], loaded["data"]["sentence_spans"],
                                                            settings.enrichment.keyphrases_include_code),
                              settings.enrichment, settings.enrichment.keyphrases_per_document)
        rows.append({"source_key": key, "chunks": len(chunks), "characters": sum(len(chunk["text"]) for chunk in chunks),
                     "entities": found, "entities_ms": round((middle - started) * 1000, 1),
                     "keyphrases_ms": round((time.perf_counter() - middle) * 1000, 1) if available else None})
    return rows


def provenance(settings, gold: dict, fixtures_path: Path, config: dict, state: dict) -> dict:
    from techdocqa.enrichment import keyphrases
    from techdocqa.evaluation.runner import environment
    from techdocqa.segmentation import spacy_version
    root = Path(__file__).resolve().parents[3]
    versions = {}
    for name in ("spacy", "rake-nltk", "nltk"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    categories = [[category.name, category.description] for category in settings.enrichment.categories]
    return {"corpus": state["summary"], "enrichment_config": config["ids"], "gazetteer_sha256": config["gazetteer"].sha256,
            "category_descriptions_sha256": hashlib.sha256(json.dumps(categories, separators=(",", ":")).encode()).hexdigest(),
            "gold_files": {name: {key: value for key, value in item.items() if key != "rows"} | ({"rows": len(item["rows"])} if "rows" in item else {})
                           for name, item in gold.items()},
            "out_of_topic": {"path": Path(fixtures_path).as_posix(), "sha256": sha256_file(fixtures_path)},
            "requirements_lock_sha256": sha256_file(root / "requirements.lock.txt"),
            "nlp_libraries": versions, "spacy_model": None, "segmenter_available": spacy_version() is not None,
            "keyphrases_available": keyphrases.rake_version() is not None,
            "environment": environment(settings, ("bm25", "vector"))}


def notes(report: dict) -> list[str]:
    found = ["Indicative only: the gold sets are the requirement minimums (P9-9). Every rate carries its denominator and a "
             "Wilson 95% interval; a target met only at the point estimate is reported that way."]
    waiting = [name for name, item in report["provenance"]["gold_files"].items() if item["status"] != "frozen"]
    if waiting:
        found.append(f"Awaiting frozen gold data: {', '.join(waiting)}. Those criteria are not measured until the owner labels "
                     "and freezes them (datasets/nlp/review_log.md).")
    if report["entities"].get("tuned"):
        found.append("The gazetteer changed after the entity sample was drawn, so the entity figures are tuned, not held out (P9-9).")
    classification = report["classification"]
    if classification.get("status") == "scored":
        found.append("The 20 public documents both calibrate the unclassified threshold and are assessed by AC-09.1, so that side is "
                     "not independent. The held-out out-of-topic fixtures were not used to choose the threshold.")
        found.append("Category scores are cosine similarities between a document's mean chunk vector and each description vector, "
                     "not probabilities.")
    found.append("DDIA and every other document outside the manifest's evaluation scope were not read.")
    return found


def run_enrichment_evaluation(manifest_path: Path, gold_directory: Path, settings, registry) -> dict:
    from techdocqa.enrichment.pipeline import configuration
    from techdocqa.evaluation.runner import corpus_state, load_manifest
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    manifest = load_manifest(manifest_path)
    config = configuration(settings)
    scope = Scope(manifest, settings, registry)
    gold = gold_sets(gold_directory)
    fixtures = Path(gold_directory) / OUT_OF_TOPIC
    durations, report = {}, {}
    for name, step in (("segmentation", lambda: score_segmentation(gold["segmentation"], scope)),
                       ("entities", lambda: score_entities(gold["entities"], scope, settings)),
                       ("keyphrases", lambda: score_keyphrases(gold["keyphrases"], scope, settings)),
                       ("classification", lambda: score_classification(scope, settings, registry, fixtures)),
                       ("corpus_checks", lambda: corpus_checks(scope, settings, registry, config)),
                       ("enrichment_times", lambda: enrichment_times(scope, settings))):
        begun = time.perf_counter()
        report[name] = step()
        durations[name] = round(time.perf_counter() - begun, 3)
    state = corpus_state(manifest, settings, registry)
    report = {"run_id": "enrichment_" + uuid.uuid4().hex, "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
              "duration_seconds": round(time.perf_counter() - started, 3), "stage_seconds": durations,
              "scope": {"documents": len(scope.records), "unavailable": scope.missing}, "targets": TARGETS,
              **report, "provenance": provenance(settings, gold, fixtures, config, state)}
    report["acceptance"] = acceptance(report)
    report["notes"] = notes(report)
    return report


def acceptance(report: dict) -> list[dict]:
    segmentation, entities, phrases = report["segmentation"], report["entities"], report["keyphrases"]
    classification, checks = report["classification"], report["corpus_checks"]
    spacy = segmentation.get("policies", {}).get("spacy", {})

    def status(section, key):
        return section.get(key) or section.get("status")

    rows = [{"criterion": "AC-06.4", "target": "boundary F1 >= 0.95 on >= 50 sentences (spaCy policy)",
             "result": spacy.get("boundary_f1"), "verdict": status(segmentation, "ac_06_4")},
            {"criterion": "AC-07.4", "target": "precision >= 0.80, recall >= 0.60 on >= 20 chunks",
             "result": [entities.get("precision", {}).get("value"), entities.get("recall", {}).get("value")],
             "verdict": status(entities, "ac_07_4")},
            {"criterion": "AC-08.3", "target": "mean share of key terms in the top 10 >= 0.50 over 5 documents",
             "result": (phrases.get("variants", {}).get(phrases.get("configured")) or {}).get("mean_hit_rate"),
             "verdict": status(phrases, "ac_08_3")},
            {"criterion": "AC-09.1", "target": "accuracy >= 0.85, >= 2 documents per category",
             "result": classification.get("ac_09_1", {}).get("accuracy_with_threshold", {}).get("value"),
             "verdict": classification.get("ac_09_1", {}).get("verdict", classification.get("status"))},
            {"criterion": "AC-09.2", "target": "the out-of-topic cooking article is unclassified (result: held-out fixtures unclassified)",
             "result": classification.get("ac_09_2", {}).get("held_out_unclassified", {}).get("value"),
             "verdict": classification.get("ac_09_2", {}).get("verdict", classification.get("status"))}]
    for criterion, key in (("AC-07.2", "ac_07_2"), ("AC-07.3", "ac_07_3"), ("AC-08.1", "ac_08_1"), ("AC-09.3", "ac_09_3")):
        rows.append({"criterion": criterion + " (real corpus)", "target": "see the corpus checks", "result": None,
                     "verdict": checks.get(key, {}).get("verdict", checks.get("status"))})
    return rows


# Report

def display(key: str) -> str:
    """A source key for people: a local file's key is a JSON pair of file name and logical name."""
    if key.startswith("["):
        try:
            name, logical = json.loads(key)
            return name if logical is None else f"{name} ({logical})"
        except (ValueError, TypeError):
            return key
    return key


def fmt(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def shown(item: dict | None) -> str:
    """A rate as 'value (k of n, 95% low-high)'."""
    if not item or item.get("value") is None:
        return "n/a"
    interval = item["interval"]
    return f"{item['value']:.3f} ({item['numerator']} of {item['denominator']}, 95% {interval['low']:.3f}-{interval['high']:.3f})"


def threshold_block(proposal: dict, run_id: str) -> str:
    return "\n".join(["[enrichment]", f"unclassified_threshold = {proposal['unclassified_threshold']}",
                      f'calibration_run_id = "{run_id}"', f'similarity_config_id = "{proposal["similarity_config_id"]}"'])


def render_markdown(report: dict) -> str:
    prov = report["provenance"]
    corpus = prov["corpus"]
    code = prov["environment"]["code"]
    lines = [f"# Enrichment evaluation {report['run_id']}", "",
             f"- Date: {report['started_at']}, {report['duration_seconds']} s",
             f"- Corpus: `{corpus['manifest_dataset_id']}`, {report['scope']['documents']} of {corpus['scope_documents']} documents, "
             f"fingerprint `{corpus['corpus_fingerprint']}`",
             f"- Code: {code['commit']} (dirty: {code['dirty']}); enrichment configuration `{prov['enrichment_config']['enrichment_config_id']}`",
             f"- Gazetteer SHA-256 `{prov['gazetteer_sha256']}`; category descriptions SHA-256 `{prov['category_descriptions_sha256']}`",
             "- Gold data: " + "; ".join(f"{name} {item['status'].replace('_', ' ')}" + (f" (`{item['sha256'][:12]}`, {item['rows']} rows)"
                                                                                         if item.get("sha256") else "")
                                         for name, item in prov["gold_files"].items()),
             f"- Out-of-topic fixtures: `{prov['out_of_topic']['path']}` SHA-256 `{prov['out_of_topic']['sha256']}`",
             "", "## Acceptance", "", "| Criterion | Target | Result | Verdict |", "|---|---|---|---|"]
    for row in report["acceptance"]:
        result = row["result"]
        value = " / ".join(fmt(item) for item in result) if isinstance(result, list) else fmt(result)
        lines.append(f"| {row['criterion']} | {row['target']} | {value} | {str(row['verdict']).replace('_', ' ')} |")
    lines += segmentation_lines(report["segmentation"]) + entity_lines(report["entities"]) + keyphrase_lines(report["keyphrases"])
    lines += classification_lines(report["classification"], report["run_id"]) + check_lines(report["corpus_checks"])
    times = report["enrichment_times"]
    lines += ["", "## Run times", "", f"Stages (s): " + ", ".join(f"{name} {value}" for name, value in report["stage_seconds"].items()), "",
              "In-memory extraction per document (P9-12):", "", "| Document | Chunks | Characters | Entities | Entities ms | Keyphrases ms |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {display(row['source_key'])} | {row['chunks']} | {row['characters']} | {row['entities']} | {row['entities_ms']} | "
              f"{'n/a' if row['keyphrases_ms'] is None else row['keyphrases_ms']} |" for row in times]
    lines += ["", "## Provenance", "", "```json", json.dumps({key: value for key, value in prov.items() if key != "environment"},
                                                              indent=1, sort_keys=True), "```", "", "## Notes", ""]
    lines += [f"- {note}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


def segmentation_lines(section: dict) -> list[str]:
    lines = ["", "## Sentence boundaries (AC-06.4, P9-2)", ""]
    if section["status"] != "scored":
        return lines + [f"Not measured: {section['status'].replace('_', ' ')}."]
    lines += [section["definition"], "", "| Policy | Boundary F1 | F1 from lower bounds | Precision | Recall | Exact sentences | Verdict |",
              "|---|---|---|---|---|---|---|"]
    for name, row in section["policies"].items():
        if "boundary_f1" not in row:
            lines.append(f"| {name} | {row.get('status')} | | | | | |")
            continue
        lines.append(f"| {name} (`{row['policy']}`) | {fmt(row['boundary_f1'])} | {fmt(row['boundary_f1_from_lower_bounds'])} | "
                     f"{shown(row['precision'])} | {shown(row['recall'])} | {shown(row['exact_sentences'])} | {row['verdict'].replace('_', ' ')} |")
    lines += ["", f"spaCy beats the rules: {'yes' if section['spacy_beats_rules'] else 'no'}. Flagged passages: "
                  f"{', '.join(section['flagged']) or 'none'}.", ""]
    for name, row in section["policies"].items():
        if "errors" not in row:
            continue
        lines += [f"Errors, {name}:", ""] + ([f"- {error['passage']} {error['kind']} at {error['offset']}: `{error['context']}`"
                                               for error in row["errors"]] or ["- none"]) + [""]
    return lines


def entity_lines(section: dict) -> list[str]:
    lines = ["", "## Entities (AC-07.4)", ""]
    if section["status"] != "scored":
        return lines + [f"Not measured: {section['status'].replace('_', ' ')}."]
    lines += [f"Verified mentions (confidence >= {section['threshold']}) against the labels, on (chunk, normalized text, type), "
              f"micro-averaged over {section['chunks']} chunks. Tuned: {'yes' if section['tuned'] else 'no'}.", "",
              f"- Precision {shown(section['precision'])}", f"- Recall {shown(section['recall'])}", f"- F1 {fmt(section['f1'])}", "",
              "| Type | Precision | Recall |", "|---|---|---|"]
    lines += [f"| {kind} | {shown(row['precision'])} | {shown(row['recall'])} |" for kind, row in section["by_type"].items()]
    lines += ["", "| Rule family | Precision |", "|---|---|"]
    lines += [f"| {family} | {shown(row['precision'])} |" for family, row in section["by_rule"].items()]
    for title, key in (("Technology", "by_technology"), ("Format", "by_format"), ("Ambiguous-name stratum", "by_ambiguous_stratum")):
        lines += ["", f"| {title} | Gold | Predicted | Matched | Precision | Recall |", "|---|---|---|---|---|---|"]
        lines += [f"| {group} | {row['gold']} | {row['predicted']} | {row['matched']} | {fmt(row['precision'])} | {fmt(row['recall'])} |"
                  for group, row in section[key].items()]
    diagnostics = section["diagnostics"]
    lines += ["", f"Diagnostics: ignoring type, precision {fmt(diagnostics['text_only']['precision'])} and recall "
                  f"{fmt(diagnostics['text_only']['recall'])}; including unverified mentions, precision "
                  f"{fmt(diagnostics['including_unverified']['precision'])} and recall {fmt(diagnostics['including_unverified']['recall'])}.",
              "", "Errors:", ""]
    for error in section["errors"]:
        fps = ", ".join(f"{item['text']} ({item['type']}, {item['rule']}" + (f", labeled {item['gold_type']}" if "gold_type" in item else "") + ")"
                        for item in error["false_positives"]) or "none"
        fns = ", ".join(f"{item['text']} ({item['type']})" for item in error["false_negatives"]) or "none"
        lines.append(f"- {error['chunk']}: false positives {fps}; missed {fns}")
    return lines


def keyphrase_lines(section: dict) -> list[str]:
    lines = ["", "## Key terms (AC-08.3, P9-5)", ""]
    if section["status"] != "scored":
        return lines + [f"Not measured: {section['status'].replace('_', ' ')}."]
    lines += [f"Configured variant `{section['configured']}` (RAKE metric / code blocks); the best on this gold set is "
              f"`{section['best_variant']}`.", "",
              "| Variant | Mean hit rate | Pooled terms | Mean lenient hit rate (diagnostic) |", "|---|---|---|---|"]
    lines += [f"| {name} | {fmt(row['mean_hit_rate'])} | {shown(row['pooled_terms'])} | {fmt(row['mean_lenient_hit_rate'])} |"
              for name, row in section["variants"].items()]
    for name in dict.fromkeys([section["configured"], section["best_variant"]]):
        row = section["variants"][name]
        lines += ["", f"{name}:", "", "| Document | Technology | Format | Hits | Missed | Top 10 |", "|---|---|---|---|---|---|"]
        lines += [f"| {doc['id']} | {doc['technology']} | {doc['format']} | {doc['hits']} of {doc['terms']} | {', '.join(doc['missed']) or 'none'} | "
                  f"{', '.join(doc['top'])} |" for doc in row["documents"]]
    return lines


def classification_lines(section: dict, run_id: str) -> list[str]:
    lines = ["", "## Classification (AC-09.1, AC-09.2, P9-6)", ""]
    if section["status"] != "scored":
        return lines + [f"Not measured: {section['status'].replace('_', ' ')}" + (f" ({section['error']['code']})." if "error" in section else ".")]
    active, result, out = section["active_threshold"], section["ac_09_1"], section["ac_09_2"]
    lines += [f"Policy `{section['similarity_policy']}`, similarity scale `{section['similarity_config_id']}`. Active threshold: "
              f"{active['status'].replace('_', ' ')}" + (f" ({active['unclassified_threshold']} from `{active['calibration_run_id']}`)" if active['unclassified_threshold'] is not None else "") + ".",
              "", f"- Top-1 accuracy {shown(result['top1_accuracy'])}",
              f"- Accuracy with the {result['threshold_source']} threshold {fmt(result['threshold_used'])} (below it counts as wrong) "
              f"{shown(result['accuracy_with_threshold'])}",
              f"- Rule baseline (technology entities mapped to categories, no user metadata) {shown(result['rule_baseline_accuracy'])}",
              "- Categories assigned per document at that threshold: " + ", ".join(
                  f"{count}: {number}" for count, number in result["assigned_per_document"].items()),
              "", "Confusion matrix (rows: manifest label, columns: top-1):", "",
              "| Label | " + " | ".join(result["confusion_matrix"]) + " |", "|---|" + "---|" * len(result["confusion_matrix"])]
    lines += [f"| {label} ({result['documents_per_category'][label]}) | " + " | ".join(str(value) for value in row.values()) + " |"
              for label, row in result["confusion_matrix"].items()]
    lines += ["", "| Document | Format | Label | Top categories (cosine) | Rule baseline | Assigned (proposal) |", "|---|---|---|---|---|---|"]
    for row in section["documents"]:
        if row["status"] != "scored":
            lines.append(f"| {display(row['source_key'])} | {row['format']} | {row['label']} | {row['status']} | | |")
            continue
        ranked = ", ".join(f"{name} {score:.3f}" for name, score in row["ranked"])
        lines.append(f"| {display(row['source_key'])} | {row['format']} | {row['label']} | {ranked} | {row['rule_baseline']} | "
                     f"{', '.join(row['assigned_under_proposal']) or 'unclassified'} |")
    lines += ["", "### Unclassified threshold", "", "| Fixture | Split | Topic | Chunks | Top category (cosine) | Unclassified (proposal) |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {row['id']} | {row['split']} | {row['topic']} | {row['chunks']} | {row['ranked'][0][0]} {row['ranked'][0][1]:.3f} | "
              f"{'yes' if row['unclassified_under_proposal'] else 'no'} |" for row in section["fixtures"]]
    proposal = section["proposal"]
    in_topic = [row["top_score"] for row in section["documents"] if row["status"] == "scored"]
    calibration = [row["top_score"] for row in section["fixtures"] if row["split"] == "calibration"]
    if in_topic and calibration:
        lines += ["", f"In-topic top-1 min / median / max: {min(in_topic):.6f} / {statistics.median(in_topic):.6f} / {max(in_topic):.6f}. "
                      f"Calibration out-of-topic: {min(calibration):.6f} / {statistics.median(calibration):.6f} / {max(calibration):.6f}."]
    if proposal:
        lines += ["", f"Proposed threshold {proposal['unclassified_threshold']} (`{proposal['policy']}`), margin {proposal['margin']}, "
                      f"{'separable' if proposal['separable'] else 'not separable'}: {proposal['in_topic_classified']} of {proposal['in_topic']} "
                      f"in-topic documents classified, {proposal['calibration_unclassified']} of {proposal['calibration_out_of_topic']} "
                      f"calibration fixtures unclassified, {proposal['leave_one_out_errors']} leave-one-out errors.",
                  f"Held out, judged by the {out['threshold_source']} threshold: {shown(out['held_out_unclassified'])} unclassified; cooking "
                  f"article unclassified: {'yes' if out['cooking_unclassified'] else 'no'}.",
                  "", "To adopt, set these in `[enrichment]` (this run becomes the calibration run):", "", "```toml",
                  threshold_block(proposal, run_id), "```"]
    return lines


def check_lines(section: dict) -> list[str]:
    lines = ["", "## Real-corpus checks (AC-07.2, AC-07.3, AC-08.1, AC-09.3)", ""]
    if section["status"] != "checked":
        states = section.get("enrichment", {})
        counts = {value: list(states.values()).count(value) for value in sorted(set(states.values()))}
        return lines + [f"Not run: {section['reason']} ({', '.join(f'{k} {v}' for k, v in counts.items()) or 'no documents'}). Run `enrich` first."]
    lines += [f"- AC-07.2: {section['ac_07_2']['entities']} entity rows, {section['ac_07_2']['invalid']} with a chunk, document or offset "
              f"that does not match: {section['ac_07_2']['verdict'].replace('_', ' ')}."]
    for key, name in (("ac_07_3", "AC-07.3"), ("ac_09_3", "AC-09.3")):
        modes = "; ".join(f"{mode} {row.get('results', 0)} results, {row.get('outside', 'n/a')} outside the filter" for mode, row in section[key]["modes"].items())
        lines.append(f"- {name} `{section[key]['filter']}`: {modes}: {section[key]['verdict'].replace('_', ' ')}.")
    lines.append(f"- AC-08.1: {section['ac_08_1']['documents']} documents, invalid keyphrase lists: "
                 f"{', '.join(section['ac_08_1']['invalid']) or 'none'}: {section['ac_08_1']['verdict'].replace('_', ' ')}.")
    return lines


def write_enrichment_report(report: dict, directory: Path) -> dict:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {"json": directory / f"{report['run_id']}.json", "markdown": directory / f"{report['run_id']}.md"}
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    return {name: path.as_posix() for name, path in paths.items()}


def summary(report: dict) -> dict:
    return {"run_id": report["run_id"], "duration_seconds": report["duration_seconds"],
            "acceptance": {row["criterion"]: row["verdict"] for row in report["acceptance"]},
            "proposal": (report["classification"].get("proposal") if isinstance(report["classification"], dict) else None)}
