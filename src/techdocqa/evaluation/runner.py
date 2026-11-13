"""Reproducible smoke runs through the same search the CLI uses, scoped to the frozen evaluation manifest.

Labels resolve to current chunks on every run. A label whose source was deleted, withdrawn or left the scope,
or whose anchor no longer matches, flags its question; the question is excluded from the metrics and listed,
and the benchmark file is never changed (FR-21, AC-21.3).
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time
import uuid

from techdocqa import __version__
from techdocqa.errors import TechDocQAError
from techdocqa.evaluation.dataset import load_dataset
from techdocqa.evaluation.metrics import (BOOTSTRAP_CONFIDENCE, BOOTSTRAP_POLICY, BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, K_VALUES,
                                          METRIC_POLICY, METRICS, P0_METRICS, macro_average, p95, paired_bootstrap, question_metrics)
from techdocqa.ingestion.chunks import stored_chunks
from techdocqa.retrieval.search import COMPONENTS, search
from techdocqa.schemas import SearchRequest

# The four FR-19 configurations, each a search mode and a rerank flag. The default stays the two P0 modes.
CONFIGURATIONS = {"bm25": ("bm25", False), "vector": ("vector", False), "hybrid": ("hybrid", False), "hybrid+rerank": ("hybrid", True)}
MODES = ("bm25", "vector")
# P10-6: candidate against baseline. The first pair is descriptive; the other two are the measured-benefit rule's.
COMPARISONS = (("vector", "bm25"), ("hybrid", "vector"), ("hybrid+rerank", "hybrid"))
BENEFIT_RULE = {("hybrid", "vector"), ("hybrid+rerank", "hybrid")}
PAIRED_METRICS = ("ndcg@5", "recall@5", "mrr")
BENEFIT_METRIC = "ndcg@5"
LATENCY_LIMIT_SECONDS = 5.0
# results_fingerprint covers exactly the P0 summary (AC-19.4): later additions are derived from fingerprinted ranks,
# and leaving them out keeps the P0 baseline 48ce89dc...a3af410 comparable across phases.
P0_SUMMARY_KEYS = ("mode", "status", "error", "retrieval_config_id", "evaluated_questions", "excluded_questions", "metrics",
                   "by_technology", "answerable_top_score", "answerable_top_relevance", "unanswerable", "refusal_calibration")
LIBRARIES = ("langchain-core", "langchain-community", "langchain-chroma", "langchain-ollama", "chromadb", "rank-bm25", "pydantic", "numpy")
SCORE_DIGITS = 6
TIME_LIMIT_SECONDS = 300


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        documents = {item["source_key"]: item for item in manifest["documents"] if item["evaluation_included"]}
        return {"dataset_id": manifest["dataset_id"], "status": manifest.get("status"),
                "fingerprint": manifest.get("reference_fingerprint_sha256"), "documents": documents}
    except (OSError, ValueError, KeyError, TypeError):
        raise TechDocQAError("MANIFEST_NOT_READABLE", "The corpus manifest is unreadable or invalid.", stage="evaluation") from None


def corpus_state(manifest: dict, settings, registry) -> dict:
    """Where each in-scope source stands now; only eligible sources contribute chunks."""
    eligible = {record.source_key: record for record in registry.eligible_versions()}
    current = {record.source_key: record for record in registry.list_documents()}
    deleted = registry.deleted_document_ids()
    sources, chunks, drift, identity = {}, {}, [], []
    for source_key, entry in sorted(manifest["documents"].items()):
        record = eligible.get(source_key)
        if record is not None:
            sources[source_key] = None
            chunks[source_key] = [(chunk, normalized(chunk["text"]), normalized(" > ".join(chunk["section_path"])))
                                  for chunk in stored_chunks(record, settings)]
            identity.append([source_key, record.version_id, record.content_hash, record.chunking.chunking_config_id, record.chunking.snapshot_hash])
            if record.content_hash != entry.get("content_hash"):
                drift.append(source_key)
        elif source_key in current:
            sources[source_key] = "SOURCE_NOT_ACTIVE"
        elif entry.get("document_id") in deleted:
            sources[source_key] = "SOURCE_DELETED"
        else:
            sources[source_key] = "SOURCE_NOT_REGISTERED"
    return {
        "sources": sources, "chunks": chunks,
        "summary": {
            "manifest_dataset_id": manifest["dataset_id"], "manifest_status": manifest["status"],
            "manifest_fingerprint": manifest["fingerprint"], "scope_documents": len(manifest["documents"]),
            "searchable_documents": len(chunks), "searchable_chunks": sum(len(items) for items in chunks.values()),
            "excluded_eligible_documents": len(set(eligible) - set(manifest["documents"])),
            "unavailable": {key: reason for key, reason in sources.items() if reason},
            "content_drift": drift,
            "corpus_fingerprint": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(),
        },
    }


def resolve(item, state) -> tuple[set[str], str | None]:
    if item.source_key not in state["sources"]:
        return set(), "SOURCE_OUT_OF_SCOPE"
    if state["sources"][item.source_key]:
        return set(), state["sources"][item.source_key]
    anchor = normalized(item.anchor) if item.anchor else None
    section = normalized(item.section) if item.section else None
    found = {chunk["chunk_id"] for chunk, text, path in state["chunks"][item.source_key]
             if (anchor is None or anchor in text) and (section is None or path == section or path.startswith(section + " > "))}
    return found, None if found else "ANCHOR_UNRESOLVED"


def label_questions(dataset, state) -> list[dict]:
    labeled = []
    for question in dataset.questions:
        chunk_items, relevant, grades, items, flags = {}, set(), {}, [], []
        for index, item in enumerate(question.relevant):
            item_id = f"{question.id}#{index}"
            found, reason = resolve(item, state)
            if reason:
                flags.append({"item": item_id, "source_key": item.source_key, "reason": reason})
            grades[item_id] = item.grade
            if item.grade > 0:
                relevant.add(item_id)
            for chunk_id in found:
                chunk_items.setdefault(chunk_id, set()).add(item_id)
            items.append({"item": item_id, "source_key": item.source_key, "grade": item.grade, "resolved_chunks": len(found)})
        # Grade-0 items are labeled non-relevant, so they never count as a hit.
        chunk_items = {chunk: hits & relevant for chunk, hits in chunk_items.items()}
        labeled.append({"question": question, "relevant": relevant, "grades": grades, "chunk_items": chunk_items, "items": items,
                        "flags": flags})
    return labeled


def spread(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"min": round(min(values), SCORE_DIGITS), "median": round(statistics.median(values), SCORE_DIGITS),
            "max": round(max(values), SCORE_DIGITS)}


def rounded(values: dict) -> dict:
    return {name: maybe(value) for name, value in values.items()}


def maybe(value: float | None) -> float | None:
    return None if value is None else round(value, SCORE_DIGITS)


def component_tops(row: dict, top_k: int) -> dict[str, float | None]:
    """Hybrid: each component's best relevance among the first top_k results, which its min_top_score judges."""
    return {name: max(values) if (values := [value for value in row["relevances"][name][:top_k] if value is not None]) else None
            for name in COMPONENTS}


def run_mode(name: str, labeled: list[dict], scope: frozenset, settings, registry) -> tuple[dict, dict]:
    """One configuration over every question; `name` is a key of CONFIGURATIONS."""
    mode, rerank = CONFIGURATIONS[name]
    # A reranked run keeps the reranker's raw score; its relevance is the reranker's 0-1 scale.
    score_key = "rerank" if rerank else mode
    per_question, config_id, degraded = {}, None, []
    started = time.perf_counter()
    try:
        for entry in labeled:
            question = entry["question"]
            request = SearchRequest(query=question.question, mode=mode, rerank=rerank, top_k=max(K_VALUES))
            begun = time.perf_counter()
            response = search(request, settings, registry, source_keys=scope)
            latency = time.perf_counter() - begun
            config_id = response.retrieval_config_id
            if response.degraded:
                # The configuration fails below; a degraded row is not this configuration's result.
                degraded.append(f"{response.failed_retriever or 'reranker'} {response.degradation_reason}")
                continue
            matches = [entry["chunk_items"].get(result.chunk_id, set()) for result in response.results]
            row = {"ranked": [result.chunk_id for result in response.results],
                   "scores": [round(result.scores[score_key], SCORE_DIGITS) for result in response.results],
                   "relevance": [maybe(result.relevance) for result in response.results],
                   "matched_items": [sorted(items) for items in matches],
                   "latency_seconds": round(latency, 3)}
            if mode == "hybrid":
                # Both component relevances of every fused result: the hybrid gate judges these (P10-3).
                row["relevances"] = {name: [maybe(result.relevances.get(name)) for result in response.results] for name in COMPONENTS}
            if not question.unanswerable and not entry["flags"]:
                row["first_relevant_rank"] = next((rank for rank, items in enumerate(matches, 1) if items), None)
                row["metrics"] = rounded(question_metrics(matches, entry["grades"]))
            per_question[question.id] = row
    except TechDocQAError as error:
        detail = error.response.error
        return {"mode": name, "status": "failed", "error": {"code": detail.code, "message": detail.message},
                "duration_seconds": round(time.perf_counter() - started, 3)}, {}
    if degraded:
        # A degraded search answers from one retriever, so the run would not measure this configuration.
        reasons = ", ".join(f"{reason} {count}" for reason, count in sorted(Counter(degraded).items()))
        return {"mode": name, "status": "failed",
                "error": {"code": "SEARCH_DEGRADED", "message": f"{len(degraded)} of {len(labeled)} searches were degraded: {reasons}."},
                "duration_seconds": round(time.perf_counter() - started, 3)}, {}
    scored = [(entry["question"], per_question[entry["question"].id]) for entry in labeled]
    answered = [(question, row) for question, row in scored if "metrics" in row]
    unanswerable = [row for question, row in scored if question.unanswerable]
    by_technology = {}
    for question, row in answered:
        by_technology.setdefault(question.technology or "unspecified", []).append(row["metrics"])
    latencies = [row["latency_seconds"] for _, row in scored]
    summary = {
        "mode": name, "status": "completed", "retrieval_config_id": config_id,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "latency_seconds": {"median": round(statistics.median(latencies), 3), "p95": p95(latencies), "max": max(latencies)},
        "evaluated_questions": len(answered),
        "excluded_questions": sum(1 for entry in labeled if not entry["question"].unanswerable and entry["flags"]),
        "metrics": rounded(macro_average([row["metrics"] for _, row in answered])),
        "by_technology": {technology: {"questions": len(rows), **rounded(macro_average(rows))}
                          for technology, rows in sorted(by_technology.items())},
        # Raw score scales differ by mode; relevance is each mode's 0-1 scale, which FR-18 thresholds use.
        "answerable_top_score": spread([row["scores"][0] for _, row in answered if row["scores"]]),
        "answerable_top_relevance": spread([row["relevance"][0] for _, row in answered if row["relevance"] and row["relevance"][0] is not None]),
        "unanswerable": {"questions": len(unanswerable), "with_results": sum(1 for row in unanswerable if row["ranked"]),
                         "top_score": spread([row["scores"][0] for row in unanswerable if row["scores"]]),
                         "top_relevance": spread([row["relevance"][0] for row in unanswerable if row["relevance"] and row["relevance"][0] is not None])},
        "refusal_calibration": refusal_calibration(mode, [row for _, row in answered], unanswerable, settings, rerank=rerank),
    }
    if mode == "hybrid":
        top_k = settings.retrieval.top_k
        summary["component_top_relevance"] = {
            group: {name: spread([value for row in rows if (value := component_tops(row, top_k)[name]) is not None]) for name in COMPONENTS}
            for group, rows in (("answerable", [row for _, row in answered]), ("unanswerable", unanswerable))}
    return summary, per_question


def refusal_calibration(mode: str, answered: list[dict], unanswerable: list[dict], settings, *, rerank: bool = False) -> dict:
    """FR-18 on this run's scores: thresholds proposed from them, and how the active thresholds judge them.

    Both judge the top results as retrieved, before any context trimming. A proposal changes nothing until a person
    copies its section into the configuration; the run that proposed it becomes the calibration run.
    """
    from techdocqa.answering import sufficiency
    from techdocqa.retrieval.search import scoring_config_id
    profile = None
    if mode in ("vector", "hybrid"):
        from techdocqa.indexing.embeddings import embedding_profile
        profile = embedding_profile(settings.model)
    top_k = settings.retrieval.top_k
    if rerank:
        return rerank_refusal_calibration(mode, answered, unanswerable, settings)
    if mode == "hybrid":
        return hybrid_refusal_calibration(answered, unanswerable, settings, profile)
    def top(rows):
        return [row["relevance"][0] if row["relevance"] else None for row in rows]
    thresholds, warning = sufficiency.active_thresholds(mode, settings, profile)
    active = {"status": "calibrated" if thresholds else ("stale" if warning == sufficiency.STALE else "not_calibrated")}
    if thresholds:
        verdicts = [[sufficiency.judge(row["relevance"][:top_k], thresholds)[1] for row in rows] for rows in (answered, unanswerable)]
        active.update(thresholds.model_dump(exclude={"scoring_config_id"}), answerable=len(answered), answerable_passed=sum(verdicts[0]),
                      unanswerable=len(unanswerable), unanswerable_refused=len(unanswerable) - sum(verdicts[1]))
    return {"relevance_policy": sufficiency.relevance_policy(mode), "scoring_config_id": scoring_config_id(mode, settings, profile),
            "active": active, "proposed": sufficiency.propose(top(answered), top(unanswerable))}


def rerank_refusal_calibration(mode: str, answered: list[dict], unanswerable: list[dict], settings) -> dict:
    """P10-4: the reranker's own scale and thresholds, bound to this reranker and this base mode's candidates."""
    from techdocqa.answering import sufficiency
    top_k = settings.retrieval.top_k
    def top(rows):
        return [row["relevance"][0] if row["relevance"] else None for row in rows]
    thresholds, warning = sufficiency.active_rerank_thresholds(mode, settings)
    active = {"status": "calibrated" if thresholds else ("stale" if warning == sufficiency.STALE else "not_calibrated")}
    if thresholds:
        verdicts = [[sufficiency.judge(row["relevance"][:top_k], thresholds)[1] for row in rows] for rows in (answered, unanswerable)]
        active.update(thresholds.model_dump(exclude={"scoring_config_id"}), answerable=len(answered), answerable_passed=sum(verdicts[0]),
                      unanswerable=len(unanswerable), unanswerable_refused=len(unanswerable) - sum(verdicts[1]))
    return {"relevance_policy": sufficiency.relevance_policy("reranked"), "section": "reranked",
            "scoring_config_id": sufficiency.rerank_scoring_config_id(mode, settings), "active": active,
            "proposed": sufficiency.propose(top(answered), top(unanswerable))}


def hybrid_refusal_calibration(answered: list[dict], unanswerable: list[dict], settings, profile: dict) -> dict:
    """P10-3 on this run: every gate's proposal with the selection, and how the active hybrid gate judges the run."""
    from techdocqa.answering import sufficiency
    from techdocqa.retrieval.search import scoring_config_id
    top_k = settings.retrieval.top_k
    thresholds, warning = sufficiency.active_thresholds("hybrid", settings, profile)
    active = {"status": "calibrated" if thresholds else ("stale" if warning == sufficiency.STALE else "not_calibrated")}
    if thresholds:
        def passes(row):
            values = {name: [value for value in row["relevances"][name][:top_k] if value is not None] for name in COMPONENTS}
            return sufficiency.judge_gate(values, thresholds)[1]
        verdicts = [[passes(row) for row in rows] for rows in (answered, unanswerable)]
        active.update(gate=thresholds.gate, calibration_run_id=thresholds.calibration_run_id,
                      thresholds={name: levels.min_top_score for name, levels in thresholds.components().items()},
                      answerable=len(answered), answerable_passed=sum(verdicts[0]),
                      unanswerable=len(unanswerable), unanswerable_refused=len(unanswerable) - sum(verdicts[1]))
    return {"relevance_policy": sufficiency.relevance_policy("hybrid"), "gate_selection": sufficiency.HYBRID_SELECTION_POLICY,
            "scoring_config_id": scoring_config_id("hybrid", settings, profile), "active": active,
            "proposed": sufficiency.propose_hybrid([component_tops(row, top_k) for row in answered],
                                                   [component_tops(row, top_k) for row in unanswerable])}


def fingerprinted(summary: dict) -> dict:
    """The P0 part of a configuration summary: P0 keys only, and only P0 metrics."""
    kept = {key: value for key, value in summary.items() if key in P0_SUMMARY_KEYS}
    if "metrics" in kept:
        kept["metrics"] = {name: kept["metrics"][name] for name in P0_METRICS}
        kept["by_technology"] = {technology: {name: values[name] for name in ("questions",) + P0_METRICS}
                                 for technology, values in kept["by_technology"].items()}
    return kept


def comparisons(configurations: list[dict], questions: list[dict]) -> list[dict]:
    """Paired per-question differences, candidate minus baseline, over questions evaluated in both (P10-6, P10-7).

    Computed from the rounded per-question metrics stored in the report, so the intervals can be recomputed from it.
    """
    completed = {row["mode"]: row for row in configurations if row["status"] == "completed"}
    found = []
    for candidate, baseline in COMPARISONS:
        if candidate not in completed or baseline not in completed:
            continue
        paired = [(question["results"][candidate]["metrics"], question["results"][baseline]["metrics"]) for question in questions
                  if "metrics" in question["results"].get(candidate, {}) and "metrics" in question["results"].get(baseline, {})]
        if not paired:
            continue
        entry = {"candidate": candidate, "baseline": baseline, "questions": len(paired), "metrics": {}}
        for name in PAIRED_METRICS:
            result = paired_bootstrap([ours[name] - theirs[name] for ours, theirs in paired])
            entry["metrics"][name] = {**result, "mean_difference": round(result["mean_difference"], SCORE_DIGITS),
                                      "interval": [round(value, SCORE_DIGITS) for value in result["interval"]]}
        if (candidate, baseline) in BENEFIT_RULE:
            lower = entry["metrics"][BENEFIT_METRIC]["interval"][0]
            latency = completed[candidate]["latency_seconds"]["p95"]
            entry["benefit_rule"] = {"interval_above_zero": lower > 0, "p95_latency_seconds": latency,
                                     "latency_within_limit": latency <= LATENCY_LIMIT_SECONDS,
                                     "measured_benefit": lower > 0 and latency <= LATENCY_LIMIT_SECONDS}
        found.append(entry)
    return found


def results_fingerprint(dataset_sha256: str, corpus_fingerprint: str, configurations: list[dict], questions: list[dict]) -> str:
    """Everything that must repeat exactly for identical inputs (AC-19.4); run ID, dates and timings are excluded."""
    repeatable = {"dataset": dataset_sha256, "corpus": corpus_fingerprint, "policy": METRIC_POLICY,
                  "configurations": [fingerprinted(summary) for summary in configurations],
                  "questions": [{"id": question["id"], "flags": question["flags"],
                                 "results": {mode: {"ranked": row["ranked"], "scores": row["scores"], "relevance": row["relevance"],
                                                    **({"relevances": row["relevances"]} if "relevances" in row else {})}
                                             for mode, row in question["results"].items()}}
                                for question in questions]}
    return hashlib.sha256(json.dumps(repeatable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def code_version() -> dict:
    root = Path(__file__).resolve().parents[3]
    def git(*arguments):
        return subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    try:
        return {"package": __version__, "commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"package": __version__, "commit": None, "dirty": None}


def environment(settings, modes) -> dict:
    from techdocqa.retrieval.lexical import TOKENIZER_POLICY
    from techdocqa.retrieval.search import fusion_values
    versions = {}
    for name in LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    model = settings.model
    values = {"code": code_version(), "python": platform.python_version(), "platform": platform.platform(),
              "libraries": versions, "provider": model.provider, "bm25": {"k1": settings.retrieval.bm25_k1,
              "b": settings.retrieval.bm25_b, "tokenizer": TOKENIZER_POLICY}, "candidate_depth": settings.retrieval.candidate_depth}
    if any(name in modes for name in ("hybrid", "hybrid+rerank")):
        values["fusion"] = fusion_values(settings)
    if any(name in modes for name in ("vector", "hybrid", "hybrid+rerank")):
        values["embedding"] = {"model": model.embedding_model, "digest": model.embedding_model_digest,
                               "dimension": model.embedding_dimension, "query_prefix": model.embedding_query_prefix}
    return values


def notes(dataset, corpus: dict, answerable: int, unanswerable: int) -> list[str]:
    drafts = sum(1 for question in dataset.questions if question.review == "draft")
    found = [f"Indicative only: {answerable} answerable and {unanswerable} unanswerable questions; "
             f"one question moves a mean by {1 / answerable:.3f}." if answerable else "No answerable questions."]
    if drafts:
        found.append(f"{drafts} of {len(dataset.questions)} questions are drafts without second-person review (FR-19); results are provisional.")
    found.append("The same questions calibrate FR-18 refusal, so calibration and this assessment overlap; this is not an independent holdout.")
    found.append(f"Results are cut at rank {max(K_VALUES)}: MRR scores 0 when the first relevant item is below that rank.")
    found.append("Precision@K credits at most one position per labeled relevant item, so a question with n labeled items "
                 "scores at most n / K.")
    if corpus["excluded_eligible_documents"]:
        found.append(f"{corpus['excluded_eligible_documents']} searchable document(s) outside the evaluation manifest were excluded from every search.")
    if corpus["manifest_status"] != "frozen":
        found.append("The corpus manifest is not marked frozen.")
    if corpus["content_drift"]:
        found.append(f"{len(corpus['content_drift'])} source(s) differ in content from the frozen manifest.")
    return found


def run_evaluation(dataset_path: Path, manifest_path: Path, settings, registry, modes=None) -> dict:
    """Run each named configuration (CONFIGURATIONS keys; default the two P0 modes) over the benchmark."""
    modes = tuple(dict.fromkeys(modes or MODES))
    unknown = [name for name in modes if name not in CONFIGURATIONS]
    if unknown:
        raise TechDocQAError("INVALID_ARGUMENT", f"Unknown configuration: {', '.join(unknown)}.", stage="evaluation")
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    dataset = load_dataset(dataset_path)
    manifest = load_manifest(manifest_path)
    state = corpus_state(manifest, settings, registry)
    labeled = label_questions(dataset, state)
    scope = frozenset(state["chunks"])
    configurations, results = [], {}
    for mode in modes:
        summary, rows = run_mode(mode, labeled, scope, settings, registry)
        configurations.append(summary)
        results[mode] = rows
    unanswerable = sum(1 for question in dataset.questions if question.unanswerable)
    answerable = len(dataset.questions) - unanswerable
    questions = [{"id": entry["question"].id, "technology": entry["question"].technology, "type": entry["question"].type,
                  "unanswerable": entry["question"].unanswerable, "review": entry["question"].review,
                  "items": entry["items"], "flags": entry["flags"],
                  "results": {mode: results[mode][entry["question"].id] for mode in modes if entry["question"].id in results[mode]}}
                 for entry in labeled]
    dataset_info = {"dataset_id": dataset.dataset_id, "path": dataset.path, "sha256": dataset.sha256,
                    "questions": len(dataset.questions), "answerable": answerable, "unanswerable": unanswerable,
                    "draft": sum(1 for question in dataset.questions if question.review == "draft"),
                    "checks": {"ds06_30_to_50_questions": 30 <= len(dataset.questions) <= 50,
                               "smoke_at_least_10_unanswerable": unanswerable >= 10,
                               "q12_20_answerable_10_unanswerable": (answerable, unanswerable) == (20, 10)}}
    duration = time.perf_counter() - started
    return {
        "run_id": "eval_" + uuid.uuid4().hex, "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 3), "within_time_limit": duration < TIME_LIMIT_SECONDS,
        "dataset": dataset_info, "corpus": state["summary"], "environment": environment(settings, modes),
        "metric_policy": {"id": METRIC_POLICY, "k": list(K_VALUES), "unit": "labeled item, counted once",
                          "average": "macro over evaluated answerable questions", "relevant_grades": [1, 2],
                          "excluded": "questions with any flagged label",
                          "credited_position": "a result holding a relevant item that no earlier result held",
                          "precision": "credited positions in the top K / K; missing results count as misses",
                          "ndcg": "gain 2^grade - 1 of the highest-graded item a credited position newly finds, discount log2(rank + 1), "
                                  "ideal from the labeled relevant items ranked by grade, one per position",
                          "fingerprint": "P0 metrics and summary only; P1 metrics are derived from the fingerprinted ranks",
                          "paired_difference": {"policy": BOOTSTRAP_POLICY, "resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                                                "confidence": BOOTSTRAP_CONFIDENCE, "metrics": list(PAIRED_METRICS),
                                                "unit": "evaluated answerable questions present in both configurations",
                                                "benefit_rule": f"P10-6: {BENEFIT_METRIC} interval lower bound > 0 and the candidate's "
                                                                f"nearest-rank p95 search latency <= {LATENCY_LIMIT_SECONDS} s; judged "
                                                                "on the full benchmark only"}},
        "configurations": configurations,
        "comparisons": comparisons(configurations, questions),
        "flags": [{"question": question["id"], **flag} for question in questions for flag in question["flags"]],
        "results_fingerprint": results_fingerprint(dataset.sha256, state["summary"]["corpus_fingerprint"], configurations, questions),
        "notes": notes(dataset, state["summary"], answerable, unanswerable),
        "questions": questions,
    }


def summary(report: dict) -> dict:
    return {key: value for key, value in report.items() if key != "questions"}


def metric(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def triple(values: dict | None) -> str:
    return "n/a" if values is None else f"{values['min']} / {values['median']} / {values['max']}"


def hybrid_refusal_lines(run_id: str, row: dict) -> tuple[list[str], list[str]]:
    from techdocqa.answering.sufficiency import hybrid_toml_block
    calibration = row["refusal_calibration"]
    proposed, active = calibration["proposed"], calibration["active"]
    lines = ["", f"### {row['mode']}: gate candidates (P10-3)", "",
             "Each question's best component relevance among its top results; G3 and G4 combine G1's and G2's thresholds. "
             "Selected by fewest leave-one-out errors, then the largest margin, then the order G1 to G4. Margins are raw, "
             "so a vector margin is on a narrower scale than a BM25 one.", ""]
    for group, label in (("answerable", "Answerable"), ("unanswerable", "Unanswerable")):
        spreads = row.get("component_top_relevance", {}).get(group, {})
        lines.append(f"- {label} min / median / max: " + "; ".join(f"{name} {triple(spreads.get(name))}" for name in COMPONENTS))
    if active["status"] == "calibrated":
        lines.append(f"- Active gate `{active['gate']}` {active['thresholds']} from `{active['calibration_run_id']}`: "
                     f"{active['answerable_passed']} of {active['answerable']} passed, {active['unanswerable_refused']} of "
                     f"{active['unanswerable']} refused")
    else:
        lines.append(f"- Active gate: {active['status'].replace('_', ' ')}")
    if proposed is None:
        return lines + ["", "No proposal: a group is empty or has fewer than two distinct scores."], []
    lines += ["", "| Gate | Thresholds | Margin | Answerable passed | Unanswerable refused | Leave-one-out errors | Selected |",
              "|---|---|---|---|---|---|---|"]
    for number, candidate in enumerate(proposed["candidates"], 1):
        values = ", ".join(f"{name} {value}" for name, value in candidate["thresholds"].items())
        lines.append(f"| {candidate['gate']} | {values} | {candidate['margin']} | {candidate['answerable_passed']} of {candidate['answerable']} | "
                     f"{candidate['unanswerable_refused']} of {candidate['unanswerable']} | {candidate['leave_one_out_errors']} | "
                     f"{'yes' if candidate['gate'] == proposed['gate'] else ''} |")
    return lines, ["", "```toml", hybrid_toml_block(proposed, run_id, calibration["scoring_config_id"]), "```"]


def refusal_lines(run_id: str, completed: list[dict]) -> list[str]:
    from techdocqa.answering.sufficiency import toml_block
    lines = ["", "## Refusal calibration (FR-18)", "",
             "Top-1 relevance on each mode's 0-1 scale, judged before context trimming. A proposal takes effect only when its "
             "section below is copied into the configuration, which makes this run the calibration run.", "",
             "| Configuration | Answerable min / median / max | Unanswerable min / median / max | Proposed threshold | Margin | "
             "Answerable passed | Unanswerable refused | Leave-one-out errors | Active thresholds |",
             "|---|---|---|---|---|---|---|---|---|"]
    blocks, gated = [], []
    for row in completed:
        calibration = row["refusal_calibration"]
        if "gate_selection" in calibration:
            lines.append(f"| {row['mode']} | see gate candidates below | | | | | | | |")
            section, block = hybrid_refusal_lines(run_id, row)
            gated += section
            blocks += block
            continue
        proposed, active = calibration["proposed"], calibration["active"]
        if active["status"] == "calibrated":
            current = (f"{active['min_top_score']} from `{active['calibration_run_id']}`: {active['answerable_passed']} of "
                       f"{active['answerable']} passed, {active['unanswerable_refused']} of {active['unanswerable']} refused")
        else:
            current = active["status"].replace("_", " ")
        if proposed is None:
            lines.append(f"| {row['mode']} | {triple(row['answerable_top_relevance'])} | {triple(row['unanswerable']['top_relevance'])} | "
                         f"none | | | | | {current} |")
            continue
        lines.append(f"| {row['mode']} | {triple(row['answerable_top_relevance'])} | {triple(row['unanswerable']['top_relevance'])} | "
                     f"{proposed['min_top_score']} | {proposed['margin']} | {proposed['answerable_passed']} of {proposed['answerable']} | "
                     f"{proposed['unanswerable_refused']} of {proposed['unanswerable']} | {proposed['leave_one_out_errors']} | {current} |")
        blocks += ["", "```toml", toml_block(calibration.get("section", row["mode"]), proposed, run_id, calibration["scoring_config_id"]), "```"]
    return lines + gated + blocks


def comparison_lines(report: dict) -> list[str]:
    policy = report["metric_policy"]["paired_difference"]
    lines = ["", "## Paired differences", "",
             f"Candidate minus baseline per question, over the answerable questions evaluated in both; mean with a "
             f"{policy['confidence']:.0%} percentile bootstrap interval ({policy['resamples']:,} resamples, seed {policy['seed']}). "
             f"Indicative. {policy['benefit_rule']}.", ""]
    if not report["comparisons"]:
        return lines + ["No pair of completed configurations to compare."]
    lines += ["| Candidate | Baseline | Questions | Metric | Mean difference | 95% interval | Better / tied / worse | Benefit rule |",
              "|---|---|---|---|---|---|---|---|"]
    for entry in report["comparisons"]:
        for name, values in entry["metrics"].items():
            rule = ""
            if "benefit_rule" in entry and name == BENEFIT_METRIC:
                verdict = entry["benefit_rule"]
                rule = (f"{'met' if verdict['measured_benefit'] else 'not met'} (interval above 0: "
                        f"{'yes' if verdict['interval_above_zero'] else 'no'}; p95 {verdict['p95_latency_seconds']} s)")
            lines.append(f"| {entry['candidate']} | {entry['baseline']} | {values['n']} | {name} | {values['mean_difference']:+.3f} | "
                         f"{values['interval'][0]:+.3f} to {values['interval'][1]:+.3f} | {values['better']} / {values['tied']} / "
                         f"{values['worse']} | {rule} |")
    return lines


def render_markdown(report: dict) -> str:
    dataset, corpus = report["dataset"], report["corpus"]
    names = list(METRICS)
    lines = [f"# Benchmark run {report['run_id']}", "",
             f"- Date: {report['started_at']}, {report['duration_seconds']} s (limit {TIME_LIMIT_SECONDS} s: "
             f"{'met' if report['within_time_limit'] else 'NOT met'})",
             f"- Dataset: `{dataset['dataset_id']}` sha256 `{dataset['sha256']}`, {dataset['questions']} questions "
             f"({dataset['answerable']} answerable, {dataset['unanswerable']} unanswerable, {dataset['draft']} draft)",
             f"- Corpus: `{corpus['manifest_dataset_id']}`, {corpus['searchable_documents']} of {corpus['scope_documents']} documents, "
             f"{corpus['searchable_chunks']} chunks, fingerprint `{corpus['corpus_fingerprint']}`",
             f"- Code: {report['environment']['code']['commit']} (dirty: {report['environment']['code']['dirty']}), "
             f"metric policy `{report['metric_policy']['id']}`",
             f"- Results fingerprint: `{report['results_fingerprint']}`", "",
             "| Configuration | Config ID | Evaluated | Excluded | " + " | ".join(names) + " | p95 latency (s) |",
             "|---|---|---|---|" + "---|" * len(names) + "---|"]
    for row in report["configurations"]:
        if row["status"] != "completed":
            lines.append(f"| {row['mode']} | failed: {row['error']['code']} | | |" + " |" * (len(names) + 1))
            continue
        lines.append(f"| {row['mode']} | `{row['retrieval_config_id'][:15]}` | {row['evaluated_questions']} | {row['excluded_questions']} | "
                     + " | ".join(metric(row["metrics"][name]) for name in names) + f" | {row['latency_seconds']['p95']} |")
    completed = [row for row in report["configurations"] if row["status"] == "completed"]
    if completed:
        lines += ["", "## By technology", "", "| Configuration | Technology | Questions | " + " | ".join(names) + " |",
                  "|---|---|---|" + "---|" * len(names)]
        for row in completed:
            for technology, values in row["by_technology"].items():
                lines.append(f"| {row['mode']} | {technology} | {values['questions']} | " + " | ".join(metric(values[name]) for name in names) + " |")
        lines += comparison_lines(report)
        lines += ["", "## Top-1 scores", "", "Raw scores in each mode's own scale. FR-18 calibration uses the 0-1 relevance below.", "",
                  "| Configuration | Answerable min / median / max | Unanswerable min / median / max | Unanswerable with results |",
                  "|---|---|---|---|"]
        for row in completed:
            lines.append(f"| {row['mode']} | {triple(row['answerable_top_score'])} | {triple(row['unanswerable']['top_score'])} | "
                         f"{row['unanswerable']['with_results']} of {row['unanswerable']['questions']} |")
        lines += refusal_lines(report["run_id"], completed)
    lines += ["", "## Flags", ""]
    lines += [f"- {flag['question']}: {flag['reason']} ({flag['source_key']})" for flag in report["flags"]] or ["None."]
    lines += ["", "## Notes", ""] + [f"- {note}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


def write_report(report: dict, directory: Path) -> dict:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {"json": directory / f"{report['run_id']}.json", "markdown": directory / f"{report['run_id']}.md"}
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    return {name: path.as_posix() for name, path in paths.items()}
