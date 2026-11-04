"""Answer runs through the same answer_question() the CLI uses, scoped to the evaluation manifest.

The answer review covers a technology-balanced sample of answerable smoke questions, for AC-16.1 and the AC-16.6 human
review. Whether a cited chunk holds a labeled passage is an automated hint only; support is judged by a person.
The refusal check asks every smoke question, for AC-18.1 and AC-18.2.
Committed reports name chunk IDs, not chunk text. The review sheet with cited text stays in the ignored data directory.
"""

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time
import uuid

from techdocqa.answering.generation import generation_config_id, model_id
from techdocqa.evaluation.dataset import load_dataset
from techdocqa.evaluation.runner import code_version, corpus_state, label_questions, load_manifest


def select_questions(dataset, count: int) -> list:
    """Round-robin over technologies in file order, so the sample is deterministic and balanced."""
    groups = {}
    for question in dataset.questions:
        if not question.unanswerable:
            groups.setdefault(question.technology or "unspecified", []).append(question)
    selected = []
    while len(selected) < count and any(groups.values()):
        for questions in groups.values():
            if questions and len(selected) < count:
                selected.append(questions.pop(0))
    return selected


def percentile(values: list[int], fraction: float) -> int | None:
    """Nearest rank, so with 10 values p95 is the largest."""
    if not values:
        return None
    return sorted(values)[math.ceil(fraction * len(values)) - 1]


def dataset_summary(dataset) -> dict:
    return {"dataset_id": dataset.dataset_id, "sha256": dataset.sha256, "questions": len(dataset.questions),
            "reviewed": sum(1 for question in dataset.questions if question.review == "reviewed")}


def answer_environment(settings) -> dict:
    model = settings.model
    return {"code": code_version(), "provider": model.provider, "model_id": model_id(model),
            "generation_config_id": generation_config_id(settings), "context_window": model.context_window,
            "max_output_tokens": model.max_output_tokens, "temperature": model.temperature,
            "timeout_seconds": model.timeout_seconds, "strict_citations": settings.answering.strict_citations}


def statuses(responses: list[dict]) -> dict:
    return {status: sum(1 for item in responses if item["status"] == status) for status in ("answered", "no_evidence", "generation_error")}


def latencies(responses: list[dict]) -> dict:
    return {stage: {"median": statistics.median(values) if values else None, "p95": percentile(values, 0.95),
                    "max": max(values, default=None)}
            for stage in ("retrieval", "generation", "total")
            for values in [[item["latency_ms"][stage] for item in responses]]}


def run_answer_review(dataset_path: Path, manifest_path: Path, settings, registry, *, count: int = 10,
                      mode: str | None = None) -> tuple[dict, dict]:
    """The report, and the text of every cited or consulted chunk for the local review sheet."""
    from techdocqa.answering.generation import answer_question, warm_up
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    dataset = load_dataset(dataset_path)
    state = corpus_state(load_manifest(manifest_path), settings, registry)
    labeled = {entry["question"].id: entry for entry in label_questions(dataset, state)}
    scope = frozenset(state["chunks"])
    warm = warm_up(settings)
    rows = []
    for question in select_questions(dataset, count):
        response = answer_question(question.question, settings, registry, mode=mode, source_keys=scope)
        hits = labeled[question.id]["chunk_items"]
        rows.append({
            "id": question.id, "technology": question.technology, "type": question.type, "question": question.question,
            "flags": labeled[question.id]["flags"],
            "response": response.model_dump(),
            # Hints, not support: does the model's cited chunk, or any supplied chunk, hold a labeled relevant passage?
            "cites_labeled_passage": any(hits.get(citation.chunk_id) for citation in response.citations),
            "evidence_has_labeled_passage": any(hits.get(chunk_id) for chunk_id in response.evidence),
            "review": {"supported": None, "reviewer": None, "notes": None},
        })
    responses = [row["response"] for row in rows]
    answered = [item for item in responses if item["status"] == "answered" and item["answer"] and item["citations"]]
    usages = [item["usage"] for item in responses if item["usage"] and item["usage"]["prompt_tokens"] is not None]
    texts = {chunk["chunk_id"]: chunk["text"] for items in state["chunks"].values() for chunk, _, _ in items}
    shown = {citation["chunk_id"] for item in responses for citation in item["citations"] + item["context_consulted"]}
    return {
        "run_id": "answers_" + uuid.uuid4().hex, "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "dataset": dataset_summary(dataset),
        "corpus": state["summary"],
        "selection": f"first {count} answerable questions, round-robin by technology in file order",
        "environment": {**answer_environment(settings), "warm_up": warm},
        "summary": {
            "questions": len(rows),
            "statuses": statuses(responses),
            # AC-16.1: answered, non-empty, at least one citation.
            "ac_16_1": {"met": len(answered) == len(rows) and bool(rows), "answered_with_citation": len(answered)},
            "cites_labeled_passage": sum(1 for row in rows if row["cites_labeled_passage"]),
            "latency_ms": latencies(responses),
            # The context budget assumes the bound; a reported count above it would mean the budget is unsafe.
            "prompt_tokens": {"max": max((u["prompt_tokens"] for u in usages), default=None),
                              "max_bound": max((u["prompt_token_bound"] for u in usages), default=None),
                              "bound_held": all(u["prompt_tokens"] <= u["prompt_token_bound"] for u in usages)},
            "human_review": "pending: AC-16.6 needs a person to rate support against the cited chunks",
        },
        "questions": rows,
    }, {chunk_id: texts[chunk_id] for chunk_id in shown if chunk_id in texts}


def citation_line(citation: dict) -> str:
    where = " > ".join(part for part in [citation["title"], citation["section_path"]] if part)
    page = f", page {citation['page']}" if citation["page"] is not None else ""
    return f"[{citation['label']}] {where}{page} ({citation['source']}) `{citation['chunk_id'][:16]}`"


def quoted(text: str) -> list[str]:
    # Trailing spaces in model output would be Markdown line breaks; the JSON keeps the exact answer.
    return ["> " + line.rstrip() if line.strip() else ">" for line in text.splitlines()] or [">"]


def fenced(text: str) -> list[str]:
    # A fence longer than any backtick run inside keeps code blocks in the chunk from closing it.
    run = width = 0
    for character in text:
        run = run + 1 if character == "`" else 0
        width = max(width, run)
    fence = "`" * max(3, width + 1)
    return [fence + "text", *text.splitlines(), fence]


def render_markdown(report: dict, chunk_text: dict | None = None) -> str:
    summary, environment = report["summary"], report["environment"]
    lines = [f"# Answer review {report['run_id']}", "",
             f"- Date: {report['started_at']}, {report['duration_seconds']} s",
             f"- Model: `{environment['model_id']}`, generation config `{environment['generation_config_id'][:15]}`, "
             f"window {environment['context_window']}, output {environment['max_output_tokens']}, temperature {environment['temperature']}",
             f"- Dataset: `{report['dataset']['dataset_id']}` sha256 `{report['dataset']['sha256']}`; corpus fingerprint `{report['corpus']['corpus_fingerprint']}`",
             f"- Code: {environment['code']['commit']} (dirty: {environment['code']['dirty']})",
             f"- Selection: {report['selection']}", "",
             "| Check | Result |", "|---|---|",
             f"| AC-16.1 answered with a citation | {summary['ac_16_1']['answered_with_citation']} of {summary['questions']} "
             f"({'met' if summary['ac_16_1']['met'] else 'NOT met'}) |",
             "| Statuses | " + ", ".join(f"{name} {value}" for name, value in summary["statuses"].items()) + " |",
             f"| Cites a labeled passage (hint, not support) | {summary['cites_labeled_passage']} of {summary['questions']} |",
             f"| Prompt tokens, max reported / max bound | {summary['prompt_tokens']['max']} / {summary['prompt_tokens']['max_bound']} "
             f"(bound held: {summary['prompt_tokens']['bound_held']}) |"]
    for stage, values in summary["latency_ms"].items():
        lines.append(f"| {stage.capitalize()} ms, median / p95 / max | {values['median']} / {values['p95']} / {values['max']} |")
    lines += [f"| AC-16.6 human review | {summary['human_review']} |", "",
              "## Review table", "",
              "A reviewer rates each answer against its cited chunks: **yes** (every claim supported), **partly** or **no**. "
              "AC-16.6 needs at least 8 of 10 rated yes.", "",
              "| Question | Status | Citations | Labeled passage cited | Supported | Reviewer notes |", "|---|---|---|---|---|---|"]
    for row in report["questions"]:
        response = row["response"]
        lines.append(f"| {row['id']} | {response['status']}{' ' + response['reason'] if response['reason'] else ''} | "
                     f"{len(response['citations'])} | {'yes' if row['cites_labeled_passage'] else 'no'} | | |")
    for row in report["questions"]:
        response = row["response"]
        lines += ["", f"## {row['id']}", "", f"**Question:** {row['question']}", "",
                  f"Status `{response['status']}`" + (f", reason `{response['reason']}`" if response["reason"] else "")
                  + f", {response['chunks_used']} of {response['chunks_retrieved']} chunks used, "
                  f"{response['latency_ms']['total']} ms.", ""]
        lines += quoted(response["answer"] or "(no answer)")
        warnings = [warning["code"] + (f" {warning['label']}" if warning["label"] else "") for warning in response["warnings"]]
        lines += ["", "Warnings: " + ", ".join(warnings), ""]
        for citation in response["citations"] or response["context_consulted"]:
            lines.append("- " + citation_line(citation))
            if chunk_text is not None:
                lines += [""] + ["  " + line for line in fenced(chunk_text.get(citation["chunk_id"], "(chunk text unavailable)"))]
    return "\n".join(lines) + "\n"


def write_answer_report(report: dict, directory: Path, review_directory: Path, chunk_text: dict) -> dict:
    directory, review_directory = Path(directory), Path(review_directory)
    directory.mkdir(parents=True, exist_ok=True)
    review_directory.mkdir(parents=True, exist_ok=True)
    paths = {"json": directory / f"{report['run_id']}.json", "markdown": directory / f"{report['run_id']}.md",
             "review_sheet": review_directory / f"{report['run_id']}_review.md"}
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    paths["review_sheet"].write_text(render_markdown(report, chunk_text), encoding="utf-8")
    return {name: path.as_posix() for name, path in paths.items()}


AC_18_1_TARGET, AC_18_2_TARGET = 0.90, 0.85


def rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def run_refusal_check(dataset_path: Path, manifest_path: Path, settings, registry, *, mode: str | None = None) -> dict:
    """Every smoke question through answer_question(), for AC-18.1 (unanswerable refused) and AC-18.2 (answerable answered).

    The chat model is loaded first and that load is timed on its own, so a cold start cannot time out the first answer.
    An answerable question with a flagged label is listed and left out of AC-18.2, as the retrieval metrics leave it out.
    """
    from techdocqa.answering.generation import answer_question, warm_up
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    dataset = load_dataset(dataset_path)
    state = corpus_state(load_manifest(manifest_path), settings, registry)
    flags = {entry["question"].id: entry["flags"] for entry in label_questions(dataset, state)}
    scope = frozenset(state["chunks"])
    warm = warm_up(settings)
    rows = []
    for question in dataset.questions:
        response = answer_question(question.question, settings, registry, mode=mode, source_keys=scope)
        rows.append({"id": question.id, "technology": question.technology, "type": question.type,
                     "unanswerable": question.unanswerable, "flags": flags[question.id], "response": response.model_dump()})
    responses = [row["response"] for row in rows]
    answerable = [row["response"] for row in rows if not row["unanswerable"] and not row["flags"]]
    unanswerable = [row["response"] for row in rows if row["unanswerable"]]
    refused = sum(1 for item in unanswerable if item["status"] == "no_evidence")
    answered = sum(1 for item in answerable if item["status"] == "answered")
    gated = [item for item in responses if item["reason"] == "LOW_RELEVANCE"]
    first = responses[0] if responses else {}
    return {
        "run_id": "refusal_" + uuid.uuid4().hex, "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "dataset": dataset_summary(dataset), "corpus": state["summary"],
        "environment": {**answer_environment(settings), "warm_up": warm},
        "retrieval": {"mode": first.get("mode"), "retrieval_config_id": first.get("retrieval_config_id"),
                      "sufficiency": {key: value for key, value in (first.get("sufficiency") or {}).items()
                                      if key not in ("passed", "top_score", "supporting_chunks")}},
        "summary": {
            "questions": len(rows), "statuses": statuses(responses),
            "excluded": [row["id"] for row in rows if not row["unanswerable"] and row["flags"]],
            "ac_18_1": {"questions": len(unanswerable), "no_evidence": refused, "rate": rate(refused, len(unanswerable)),
                        "target": AC_18_1_TARGET, "reasons": dict(Counter(item["reason"] or item["status"] for item in unanswerable)),
                        "met": len(unanswerable) >= 10 and refused >= AC_18_1_TARGET * len(unanswerable)},
            "ac_18_2": {"questions": len(answerable), "answered": answered, "rate": rate(answered, len(answerable)),
                        "target": AC_18_2_TARGET, "reasons": dict(Counter(item["reason"] or item["status"] for item in answerable)),
                        "met": len(answerable) >= 20 and answered >= AC_18_2_TARGET * len(answerable)},
            # AC-18.1: a refusal by the gate must never have sent a chat request.
            "gate_refusals": len(gated), "llm_calls_on_gate_refusals": sum(1 for item in gated if item["llm_called"]),
            "llm_calls": sum(1 for item in responses if item["llm_called"]),
            "latency_ms": latencies(responses),
        },
        "questions": rows,
    }


def render_refusal_markdown(report: dict) -> str:
    summary, environment, retrieval = report["summary"], report["environment"], report["retrieval"]
    gate, warm = retrieval["sufficiency"], environment["warm_up"]
    first, second = summary["ac_18_1"], summary["ac_18_2"]
    thresholds = (f"min_top_score {gate['min_top_score']}, min_chunk_score {gate['min_chunk_score']}, "
                  f"min_supporting_chunks {gate['min_supporting_chunks']}, calibration run `{gate['calibration_run_id']}`"
                  if gate.get("calibrated") else "none: this mode is not calibrated, so no question was gated")
    loaded = f"loaded in {warm['ms']} ms" if warm["loaded"] else f"not loaded ({warm['code'] or 'nothing to load'})"
    lines = [f"# Refusal check {report['run_id']}", "",
             f"- Date: {report['started_at']}, {report['duration_seconds']} s",
             f"- Model: `{environment['model_id']}`, generation config `{environment['generation_config_id'][:15]}`, warm-up {loaded}",
             f"- Retrieval: {retrieval['mode']}, config `{(retrieval['retrieval_config_id'] or '')[:15]}`, "
             f"relevance policy `{gate.get('relevance_policy')}`",
             f"- Thresholds: {thresholds}",
             f"- Dataset: `{report['dataset']['dataset_id']}` sha256 `{report['dataset']['sha256']}`; "
             f"corpus fingerprint `{report['corpus']['corpus_fingerprint']}`",
             f"- Code: {environment['code']['commit']} (dirty: {environment['code']['dirty']})", "",
             "| Check | Result |", "|---|---|",
             f"| AC-18.1 unanswerable refused (`no_evidence`) | {first['no_evidence']} of {first['questions']} = {first['rate']}, "
             f"target {first['target']} ({'met' if first['met'] else 'NOT met'}) |",
             f"| AC-18.2 answerable answered | {second['answered']} of {second['questions']} = {second['rate']}, "
             f"target {second['target']} ({'met' if second['met'] else 'NOT met'}) |",
             f"| Refused by the gate / chat requests among them | {summary['gate_refusals']} / {summary['llm_calls_on_gate_refusals']} |",
             f"| Chat requests in the run | {summary['llm_calls']} of {summary['questions']} questions |",
             "| Statuses | " + ", ".join(f"{name} {value}" for name, value in summary["statuses"].items()) + " |",
             "| Unanswerable outcomes | " + ", ".join(f"{name} {value}" for name, value in sorted(first["reasons"].items(), key=str)) + " |",
             "| Answerable outcomes | " + ", ".join(f"{name} {value}" for name, value in sorted(second["reasons"].items(), key=str)) + " |"]
    for stage, values in summary["latency_ms"].items():
        lines.append(f"| {stage.capitalize()} ms, median / p95 / max | {values['median']} / {values['p95']} / {values['max']} |")
    if summary["excluded"]:
        lines.append(f"| Excluded for flagged labels | {', '.join(summary['excluded'])} |")
    lines += ["", "## Questions", "",
              "| Question | Unanswerable | Status | Reason | Top relevance | Gate passed | Chat request | Citations | Total ms |",
              "|---|---|---|---|---|---|---|---|---|"]
    for row in report["questions"]:
        response = row["response"]
        check = response["sufficiency"] or {}
        lines.append(f"| {row['id']} | {'yes' if row['unanswerable'] else 'no'} | {response['status']} | {response['reason'] or ''} | "
                     f"{check.get('top_score')} | {check.get('passed')} | {'yes' if response['llm_called'] else 'no'} | "
                     f"{len(response['citations'])} | {response['latency_ms']['total']} |")
    return "\n".join(lines) + "\n"


def write_refusal_report(report: dict, directory: Path) -> dict:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {"json": directory / f"{report['run_id']}.json", "markdown": directory / f"{report['run_id']}.md"}
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_refusal_markdown(report), encoding="utf-8")
    return {name: path.as_posix() for name, path in paths.items()}
