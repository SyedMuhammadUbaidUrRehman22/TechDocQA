"""Reproducible smoke runs through the same search the CLI uses, scoped to the frozen evaluation manifest.

Labels resolve to current chunks on every run. A label whose source was deleted, withdrawn or left the scope,
or whose anchor no longer matches, flags its question; the question is excluded from the metrics and listed,
and the benchmark file is never changed (FR-21, AC-21.3).
"""

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
from techdocqa.evaluation.metrics import K_VALUES, METRIC_POLICY, macro_average, question_metrics
from techdocqa.ingestion.chunks import stored_chunks
from techdocqa.retrieval.search import search
from techdocqa.schemas import SearchRequest

MODES = ("bm25", "vector")
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
        chunk_items, relevant, items, flags = {}, set(), [], []
        for index, item in enumerate(question.relevant):
            item_id = f"{question.id}#{index}"
            found, reason = resolve(item, state)
            if reason:
                flags.append({"item": item_id, "source_key": item.source_key, "reason": reason})
            if item.grade > 0:
                relevant.add(item_id)
            for chunk_id in found:
                chunk_items.setdefault(chunk_id, set()).add(item_id)
            items.append({"item": item_id, "source_key": item.source_key, "grade": item.grade, "resolved_chunks": len(found)})
        # Grade-0 items are labeled non-relevant, so they never count as a hit.
        chunk_items = {chunk: hits & relevant for chunk, hits in chunk_items.items()}
        labeled.append({"question": question, "relevant": relevant, "chunk_items": chunk_items, "items": items, "flags": flags})
    return labeled


def spread(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"min": round(min(values), SCORE_DIGITS), "median": round(statistics.median(values), SCORE_DIGITS),
            "max": round(max(values), SCORE_DIGITS)}


def rounded(values: dict) -> dict:
    return {name: (None if value is None else round(value, SCORE_DIGITS)) for name, value in values.items()}


def run_mode(mode: str, labeled: list[dict], scope: frozenset, settings, registry) -> tuple[dict, dict]:
    per_question, config_id = {}, None
    started = time.perf_counter()
    try:
        for entry in labeled:
            question = entry["question"]
            request = SearchRequest(query=question.question, mode=mode, top_k=max(K_VALUES))
            begun = time.perf_counter()
            response = search(request, settings, registry, source_keys=scope)
            latency = time.perf_counter() - begun
            config_id = response.retrieval_config_id
            matches = [entry["chunk_items"].get(result.chunk_id, set()) for result in response.results]
            row = {"ranked": [result.chunk_id for result in response.results],
                   "scores": [round(result.scores[mode], SCORE_DIGITS) for result in response.results],
                   "relevance": [round(result.relevance, SCORE_DIGITS) for result in response.results],
                   "matched_items": [sorted(items) for items in matches],
                   "latency_seconds": round(latency, 3)}
            if not question.unanswerable and not entry["flags"]:
                row["first_relevant_rank"] = next((rank for rank, items in enumerate(matches, 1) if items), None)
                row["metrics"] = rounded(question_metrics(matches, entry["relevant"]))
            per_question[question.id] = row
    except TechDocQAError as error:
        detail = error.response.error
        return {"mode": mode, "status": "failed", "error": {"code": detail.code, "message": detail.message},
                "duration_seconds": round(time.perf_counter() - started, 3)}, {}
    scored = [(entry["question"], per_question[entry["question"].id]) for entry in labeled]
    answered = [(question, row) for question, row in scored if "metrics" in row]
    unanswerable = [row for question, row in scored if question.unanswerable]
    by_technology = {}
    for question, row in answered:
        by_technology.setdefault(question.technology or "unspecified", []).append(row["metrics"])
    summary = {
        "mode": mode, "status": "completed", "retrieval_config_id": config_id,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "evaluated_questions": len(answered),
        "excluded_questions": sum(1 for entry in labeled if not entry["question"].unanswerable and entry["flags"]),
        "metrics": rounded(macro_average([row["metrics"] for _, row in answered])),
        "by_technology": {technology: {"questions": len(rows), **rounded(macro_average(rows))}
                          for technology, rows in sorted(by_technology.items())},
        # Raw score scales differ by mode; relevance is each mode's 0-1 scale, which FR-18 thresholds use.
        "answerable_top_score": spread([row["scores"][0] for _, row in answered if row["scores"]]),
        "answerable_top_relevance": spread([row["relevance"][0] for _, row in answered if row["relevance"]]),
        "unanswerable": {"questions": len(unanswerable), "with_results": sum(1 for row in unanswerable if row["ranked"]),
                         "top_score": spread([row["scores"][0] for row in unanswerable if row["scores"]]),
                         "top_relevance": spread([row["relevance"][0] for row in unanswerable if row["relevance"]])},
        "refusal_calibration": refusal_calibration(mode, [row for _, row in answered], unanswerable, settings),
    }
    return summary, per_question


def refusal_calibration(mode: str, answered: list[dict], unanswerable: list[dict], settings) -> dict:
    """FR-18 on this run's scores: thresholds proposed from them, and how the active thresholds judge them.

    Both judge the top results as retrieved, before any context trimming. A proposal changes nothing until a person
    copies its section into the configuration; the run that proposed it becomes the calibration run.
    """
    from techdocqa.answering import sufficiency
    from techdocqa.retrieval.search import scoring_config_id
    profile = None
    if mode == "vector":
        from techdocqa.indexing.embeddings import embedding_profile
        profile = embedding_profile(settings.model)
    top_k = settings.retrieval.top_k
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
    if "vector" in modes:
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
    if corpus["excluded_eligible_documents"]:
        found.append(f"{corpus['excluded_eligible_documents']} searchable document(s) outside the evaluation manifest were excluded from every search.")
    if corpus["manifest_status"] != "frozen":
        found.append("The corpus manifest is not marked frozen.")
    if corpus["content_drift"]:
        found.append(f"{len(corpus['content_drift'])} source(s) differ in content from the frozen manifest.")
    return found


def run_evaluation(dataset_path: Path, manifest_path: Path, settings, registry, modes=None) -> dict:
    modes = tuple(dict.fromkeys(modes or MODES))
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
    # Everything that must repeat exactly for identical inputs (AC-19.4); run ID, dates and timings are excluded.
    repeatable = {"dataset": dataset.sha256, "corpus": state["summary"]["corpus_fingerprint"], "policy": METRIC_POLICY,
                  "configurations": [{key: value for key, value in summary.items() if key != "duration_seconds"} for summary in configurations],
                  "questions": [{"id": question["id"], "flags": question["flags"],
                                 "results": {mode: {"ranked": row["ranked"], "scores": row["scores"], "relevance": row["relevance"]}
                                             for mode, row in question["results"].items()}}
                                for question in questions]}
    duration = time.perf_counter() - started
    return {
        "run_id": "eval_" + uuid.uuid4().hex, "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 3), "within_time_limit": duration < TIME_LIMIT_SECONDS,
        "dataset": dataset_info, "corpus": state["summary"], "environment": environment(settings, modes),
        "metric_policy": {"id": METRIC_POLICY, "k": list(K_VALUES), "unit": "labeled item, counted once",
                          "average": "macro over evaluated answerable questions", "relevant_grades": [1, 2],
                          "excluded": "questions with any flagged label"},
        "configurations": configurations,
        "flags": [{"question": question["id"], **flag} for question in questions for flag in question["flags"]],
        "results_fingerprint": hashlib.sha256(json.dumps(repeatable, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "notes": notes(dataset, state["summary"], answerable, unanswerable),
        "questions": questions,
    }


def summary(report: dict) -> dict:
    return {key: value for key, value in report.items() if key != "questions"}


def metric(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def triple(values: dict | None) -> str:
    return "n/a" if values is None else f"{values['min']} / {values['median']} / {values['max']}"


def refusal_lines(run_id: str, completed: list[dict]) -> list[str]:
    from techdocqa.answering.sufficiency import toml_block
    lines = ["", "## Refusal calibration (FR-18)", "",
             "Top-1 relevance on each mode's 0-1 scale, judged before context trimming. A proposal takes effect only when its "
             "section below is copied into the configuration, which makes this run the calibration run.", "",
             "| Configuration | Answerable min / median / max | Unanswerable min / median / max | Proposed threshold | Margin | "
             "Answerable passed | Unanswerable refused | Leave-one-out errors | Active thresholds |",
             "|---|---|---|---|---|---|---|---|---|"]
    blocks = []
    for row in completed:
        calibration = row["refusal_calibration"]
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
        blocks += ["", "```toml", toml_block(row["mode"], proposed, run_id, calibration["scoring_config_id"]), "```"]
    return lines + blocks


def render_markdown(report: dict) -> str:
    dataset, corpus = report["dataset"], report["corpus"]
    names = [f"recall@{k}" for k in K_VALUES] + ["mrr"]
    lines = [f"# Smoke benchmark run {report['run_id']}", "",
             f"- Date: {report['started_at']}, {report['duration_seconds']} s (limit {TIME_LIMIT_SECONDS} s: "
             f"{'met' if report['within_time_limit'] else 'NOT met'})",
             f"- Dataset: `{dataset['dataset_id']}` sha256 `{dataset['sha256']}`, {dataset['questions']} questions "
             f"({dataset['answerable']} answerable, {dataset['unanswerable']} unanswerable, {dataset['draft']} draft)",
             f"- Corpus: `{corpus['manifest_dataset_id']}`, {corpus['searchable_documents']} of {corpus['scope_documents']} documents, "
             f"{corpus['searchable_chunks']} chunks, fingerprint `{corpus['corpus_fingerprint']}`",
             f"- Code: {report['environment']['code']['commit']} (dirty: {report['environment']['code']['dirty']}), "
             f"metric policy `{report['metric_policy']['id']}`",
             f"- Results fingerprint: `{report['results_fingerprint']}`", "",
             "| Configuration | Config ID | Evaluated | Excluded | " + " | ".join(names) + " |",
             "|---|---|---|---|" + "---|" * len(names)]
    for row in report["configurations"]:
        if row["status"] != "completed":
            lines.append(f"| {row['mode']} | failed: {row['error']['code']} | | |" + " |" * len(names))
            continue
        lines.append(f"| {row['mode']} | `{row['retrieval_config_id'][:15]}` | {row['evaluated_questions']} | {row['excluded_questions']} | "
                     + " | ".join(metric(row["metrics"][name]) for name in names) + " |")
    completed = [row for row in report["configurations"] if row["status"] == "completed"]
    if completed:
        lines += ["", "## By technology", "", "| Configuration | Technology | Questions | " + " | ".join(names) + " |",
                  "|---|---|---|" + "---|" * len(names)]
        for row in completed:
            for technology, values in row["by_technology"].items():
                lines.append(f"| {row['mode']} | {technology} | {values['questions']} | " + " | ".join(metric(values[name]) for name in names) + " |")
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
