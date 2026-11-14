"""Phase 11 latency profile (P11-1): NFR-02 retrieval and NFR-03 QA p95, with stage timings, on the real index.

Usage: python scripts/profile_latency.py {retrieval,cold,qa} [options]

  retrieval  search() in this process over every benchmark question, per configuration: one uncounted warm-up per
             configuration, then --passes passes. Nearest-rank p95 per configuration, against NFR-02.
             --scope evaluation searches only the frozen manifest's documents, as eval does; --scope whole searches
             the whole local index (NFR-01 headroom, P11-3).
  cold       each configuration's first search in a fresh process, with the embedding model loaded and then unloaded,
             and the CLI's process start. Reported apart from the p95.
  qa         answer_question() for every answerable question in the configured default mode. The p95 counts only the
             questions that reached generation; gate refusals make no model call and are reported apart. A timeout
             stays in, as a time over the target.

Stage functions are wrapped only while a profile runs and are restored afterwards, so production code, schemas,
configuration IDs and fingerprints do not change. Reports hold question IDs, counts and timings only: no query result,
chunk text or chunk ID, because the whole scope includes the private supplement. They go to --report-dir, by default
<data>/evaluation, which is not tracked.
"""

import argparse
from datetime import datetime, timezone
import functools
import hashlib
import importlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROCEDURE = "p11-latency-v1"
# NFR-02 targets in seconds: without reranking, and with it. NFR-03 for a local Ollama model on CPU.
TARGETS = {"bm25": 1.0, "vector": 1.0, "hybrid": 1.0, "hybrid+rerank": 5.0}
QA_TARGET_SECONDS = 60.0
MIN_FREE_GB = 1.5
# (owner, attribute, stage, the stage it runs inside or None). An owner "module:Class" wraps a method of that class.
# Nested stages are reported but not added again when the unattributed remainder is computed.
STAGES = (
    ("techdocqa.registry:Registry", "eligible_versions", "registry_read", None),
    ("techdocqa.indexing.embeddings", "embedding_profile", "embedding_profile", None),
    ("techdocqa.retrieval.search", "bm25_ranked", "bm25_search", None),
    ("techdocqa.retrieval.lexical:LexicalIndex", "__init__", "bm25_index_build", "bm25_search"),
    ("techdocqa.retrieval.lexical:LexicalIndex", "scored", "bm25_rescore", None),
    ("techdocqa.indexing.vector_store:VectorStore", "__init__", "vector_store_open", None),
    ("techdocqa.indexing.vector_store:VectorStore", "empty", "vector_store_empty_check", None),
    ("techdocqa.indexing.embeddings", "embed_query", "query_embedding", None),
    ("techdocqa.indexing.embeddings", "build_embeddings", "embedder_build", "query_embedding"),
    ("techdocqa.indexing.vector_store:VectorStore", "search", "vector_search", None),
    ("techdocqa.retrieval.search", "stored_relevances", "stored_relevances", None),
    ("techdocqa.retrieval.rerank", "rerank", "rerank", None),
    ("techdocqa.retrieval.search", "retrieval_config_id", "config_id", None),
)
QA_STAGES = (
    ("techdocqa.answering.generation", "build_chat_model", "chat_model_build", None),
    ("techdocqa.answering.generation", "generate", "generation_call", None),
)


def resolve(owner: str):
    module, _, name = owner.partition(":")
    found = importlib.import_module(module)
    return getattr(found, name) if name else found


class StageTimer:
    """Inside the with block, every call of a listed function adds its time to the current query's record."""

    def __init__(self, stages=STAGES):
        self.stages, self.current, self.restore = stages, None, []

    def __enter__(self):
        for owner_name, attribute, stage, _ in self.stages:
            owner = resolve(owner_name)
            original = vars(owner)[attribute] if isinstance(owner, type) else getattr(owner, attribute)
            setattr(owner, attribute, self.wrapped(original, stage))
            self.restore.append((owner, attribute, original))
        return self

    def __exit__(self, *exc):
        for owner, attribute, original in reversed(self.restore):
            setattr(owner, attribute, original)
        self.restore = []
        return False

    def wrapped(self, original, stage):
        timer = self

        @functools.wraps(original)
        def timed(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                if timer.current is not None:
                    seconds, calls = timer.current.get(stage, (0.0, 0))
                    timer.current[stage] = (seconds + time.perf_counter() - started, calls + 1)
        return timed

    def begin(self):
        self.current = {}

    def end(self) -> dict:
        found, self.current = self.current or {}, None
        return {stage: {"seconds": seconds, "calls": calls} for stage, (seconds, calls) in found.items()}


def top_level(stages=STAGES) -> list[str]:
    return [stage for _, _, stage, inside in stages if inside is None]


def seconds(values: list[float]) -> dict:
    from techdocqa.evaluation.metrics import p95
    if not values:
        return {"n": 0, "median": None, "p95": None, "max": None, "mean": None}
    return {"n": len(values), "median": round(statistics.median(values), 4), "p95": round(p95(values), 4),
            "max": round(max(values), 4), "mean": round(statistics.fmean(values), 4)}


def stage_summary(timings: list[dict], stages=STAGES) -> dict:
    """Per stage over every timed query (0 where a query did not call it), and the remainder no top-level stage covers."""
    names = [stage for _, _, stage, _ in stages]
    totals = [item["total"] for item in timings]
    mean_total = statistics.fmean(totals) if totals else 0.0
    summary = {}
    for name in names:
        values = [item["stages"].get(name, {}).get("seconds", 0.0) for item in timings]
        calls = [item["stages"].get(name, {}).get("calls", 0) for item in timings]
        if not any(calls):
            continue
        stats = seconds(values)
        summary[name] = {**stats, "calls_per_query": round(statistics.fmean(calls), 3),
                         "share_of_mean": round(stats["mean"] / mean_total, 3) if mean_total else None,
                         "inside": next(inside for _, _, stage, inside in stages if stage == name)}
    rest = [item["total"] - sum(item["stages"].get(name, {}).get("seconds", 0.0) for name in top_level(stages)) for item in timings]
    stats = seconds(rest)
    summary["unattributed"] = {**stats, "calls_per_query": None,
                               "share_of_mean": round(stats["mean"] / mean_total, 3) if mean_total and rest else None, "inside": None}
    return summary


def result_digest(response) -> str:
    """Identity of a ranking, scores included; only the digest is kept, never the chunk IDs."""
    rows = [[item.chunk_id, item.scores, item.relevance, item.relevances] for item in response.results]
    return hashlib.sha256(json.dumps([rows, response.degraded], sort_keys=True, default=str).encode()).hexdigest()


def evaluation_scope(settings, registry, manifest_path: Path) -> frozenset[str]:
    from techdocqa.evaluation.runner import corpus_state, load_manifest
    return frozenset(corpus_state(load_manifest(manifest_path), settings, registry)["chunks"])


def retrieval_profile(settings, registry, dataset_path: Path, manifest_path: Path, *, scope: str = "evaluation",
                      configurations=None, passes: int = 3) -> dict:
    from techdocqa.evaluation.dataset import load_dataset
    from techdocqa.evaluation.runner import CONFIGURATIONS
    from techdocqa.evaluation.runtime import runtime
    from techdocqa.retrieval.search import search
    from techdocqa.schemas import SearchRequest
    names = list(dict.fromkeys(configurations or CONFIGURATIONS))
    unknown = [name for name in names if name not in CONFIGURATIONS]
    if unknown or scope not in ("evaluation", "whole") or passes < 1:
        raise ValueError(f"unknown configuration {unknown}, scope {scope!r} or passes {passes}")
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    dataset = load_dataset(dataset_path)
    source_keys = evaluation_scope(settings, registry, manifest_path) if scope == "evaluation" else None
    questions = dataset.questions
    before = runtime(settings)

    def request(name, question):
        mode, rerank = CONFIGURATIONS[name]
        return SearchRequest(query=question.question, mode=mode, top_k=settings.retrieval.top_k, rerank=rerank)

    timings = {name: [] for name in names}
    digests = {name: {question.id: set() for question in questions} for name in names}
    per_question = {question.id: {name: [] for name in names} for question in questions}
    with StageTimer() as timer:
        warm_up = {}
        for name in names:
            begun = time.perf_counter()
            search(request(name, questions[0]), settings, registry, source_keys=source_keys)
            warm_up[name] = round(time.perf_counter() - begun, 4)
        for _ in range(passes):
            for name in names:
                for question in questions:
                    timer.begin()
                    begun = time.perf_counter()
                    response = search(request(name, question), settings, registry, source_keys=source_keys)
                    total = time.perf_counter() - begun
                    timings[name].append({"total": total, "stages": timer.end(), "degraded": response.degraded})
                    digests[name][question.id].add(result_digest(response))
                    per_question[question.id][name].append(round(total, 4))
    configurations_out = []
    for name in names:
        totals = [item["total"] for item in timings[name]]
        stats = seconds(totals)
        configurations_out.append({
            "configuration": name, "target_seconds": TARGETS[name], "warm_up_seconds": warm_up[name], "latency_seconds": stats,
            "met": stats["p95"] is not None and stats["p95"] <= TARGETS[name],
            "degraded_searches": sum(1 for item in timings[name] if item["degraded"]),
            "changed_rankings": sum(1 for found in digests[name].values() if len(found) > 1),
            "stages": stage_summary(timings[name])})
    return {"run_id": "latency_" + uuid.uuid4().hex, "kind": "retrieval", "procedure": PROCEDURE, "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": round(time.perf_counter() - started, 3),
            "scope": scope, "scope_sources": len(source_keys) if source_keys is not None else None, "passes": passes,
            "dataset": {"dataset_id": dataset.dataset_id, "sha256": dataset.sha256, "questions": len(questions)},
            "runtime_before": before, "runtime_after": runtime(settings), "configurations": configurations_out,
            "questions": [{"id": question.id, "seconds": per_question[question.id]} for question in questions]}


def qa_profile(settings, registry, dataset_path: Path, manifest_path: Path) -> dict:
    from techdocqa.answering.generation import answer_question, warm_up
    from techdocqa.evaluation.dataset import load_dataset
    from techdocqa.evaluation.runtime import runtime
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    dataset = load_dataset(dataset_path)
    source_keys = evaluation_scope(settings, registry, manifest_path)
    answerable = [question for question in dataset.questions if not question.unanswerable]
    before = runtime(settings)
    warm = warm_up(settings)
    stages = STAGES + QA_STAGES
    rows = []
    with StageTimer(stages) as timer:
        for question in answerable:
            timer.begin()
            response = answer_question(question.question, settings, registry, source_keys=source_keys)
            rows.append({"id": question.id, "technology": question.technology, "status": response.status, "reason": response.reason,
                         "llm_called": response.llm_called, "timed_out": response.reason == "LLM_TIMEOUT",
                         "mode": response.mode, "degraded": response.degraded,
                         "seconds": {stage: value / 1000 for stage, value in response.latency_ms.model_dump().items()},
                         "stages": timer.end()})
    generated = [row for row in rows if row["llm_called"]]
    refused = [row for row in rows if not row["llm_called"]]
    by_stage = {stage: seconds([row["seconds"][stage] for row in generated]) for stage in ("retrieval", "generation", "total")}
    p95_total = by_stage["total"]["p95"]
    return {"run_id": "latency_" + uuid.uuid4().hex, "kind": "qa", "procedure": PROCEDURE, "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": round(time.perf_counter() - started, 3),
            "mode": settings.retrieval.mode, "rerank": settings.retrieval.rerank, "warm_up": warm,
            "dataset": {"dataset_id": dataset.dataset_id, "sha256": dataset.sha256, "answerable": len(answerable)},
            "runtime_before": before, "runtime_after": runtime(settings), "target_seconds": QA_TARGET_SECONDS,
            "reached_generation": len(generated), "timed_out": sum(1 for row in generated if row["timed_out"]),
            "seconds": by_stage, "met": p95_total is not None and p95_total <= QA_TARGET_SECONDS,
            "gate_refused": {"questions": len(refused), "total_seconds": seconds([row["seconds"]["total"] for row in refused])},
            "statuses": {status: sum(1 for row in rows if row["status"] == status) for status in ("answered", "no_evidence", "generation_error")},
            "stages": stage_summary([{"total": row["seconds"]["total"], "stages": row["stages"]} for row in generated], stages),
            "questions": [{key: value for key, value in row.items() if key != "stages"} for row in rows]}


def inventory() -> dict | None:
    """CPU, GPUs and RAM, and whether a test run is going on, read once per profile (Windows only)."""
    if sys.platform != "win32":
        return None
    script = ("$c = Get-CimInstance Win32_Processor; $o = Get-CimInstance Win32_OperatingSystem; "
              "$t = @(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'pytest' }).Count; "
              "[pscustomobject]@{cpu = $c.Name; cores = $c.NumberOfCores; threads = $c.NumberOfLogicalProcessors; "
              "gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object Name); "
              "ram_total_bytes = [int64]$o.TotalVisibleMemorySize * 1024; pytest_processes = $t} | ConvertTo-Json -Compress")
    try:
        found = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=120)
        return json.loads(found.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def ollama_loaded(base_url: str) -> list[str]:
    from techdocqa.evaluation.runtime import ollama_state
    return [item["model"] for item in ollama_state(base_url).get("loaded") or []]


def set_embedding_model(settings, loaded: bool) -> None:
    """Load the embedding model with one tiny request, or unload it with `ollama stop`, then wait until it shows."""
    import httpx
    model = settings.model.embedding_model
    if loaded:
        httpx.post(f"{settings.model.base_url}/api/embed", json={"model": model, "input": "warm"}, timeout=120).raise_for_status()
    else:
        subprocess.run(["ollama", "stop", model], capture_output=True, timeout=60, check=False)
    for _ in range(60):
        if (model in ollama_loaded(settings.model.base_url)) == loaded:
            return
        time.sleep(0.5)
    raise RuntimeError(f"{model} did not become {'loaded' if loaded else 'unloaded'}")


def first_search(args) -> dict:
    """Run inside a fresh process: import, set up, then the first and second search of one configuration."""
    began = time.perf_counter()
    from techdocqa.evaluation.runner import CONFIGURATIONS
    from techdocqa.registry import Registry
    from techdocqa.retrieval.search import search
    from techdocqa.schemas import SearchRequest
    from techdocqa.settings import load_settings
    imported = time.perf_counter()
    settings = load_settings(args.config, args.profile)
    from techdocqa.evaluation.dataset import load_dataset
    question = load_dataset(args.dataset).questions[0]
    with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
        source_keys = evaluation_scope(settings, registry, args.manifest)
        mode, rerank = CONFIGURATIONS[args.configuration[0]]
        request = SearchRequest(query=question.question, mode=mode, top_k=settings.retrieval.top_k, rerank=rerank)
        ready = time.perf_counter()
        with StageTimer() as timer:
            timer.begin()
            started = time.perf_counter()
            first = search(request, settings, registry, source_keys=source_keys)
            first_seconds, stages = time.perf_counter() - started, timer.end()
            started = time.perf_counter()
            search(request, settings, registry, source_keys=source_keys)
            second_seconds = time.perf_counter() - started
    return {"import_seconds": round(imported - began, 4), "setup_seconds": round(ready - imported, 4),
            "first_seconds": round(first_seconds, 4), "second_seconds": round(second_seconds, 4), "degraded": first.degraded,
            "first_stages": {name: {"seconds": round(value["seconds"], 4), "calls": value["calls"]} for name, value in stages.items()}}


def cold_profile(args, settings) -> dict:
    from techdocqa.evaluation.runner import CONFIGURATIONS
    from techdocqa.evaluation.runtime import runtime
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    before = runtime(settings)
    runs = []
    for name in list(dict.fromkeys(args.configuration or CONFIGURATIONS)):
        states = ("loaded", "unloaded") if CONFIGURATIONS[name][0] in ("vector", "hybrid") else ("not used",)
        for state in states:
            if state != "not used":
                set_embedding_model(settings, state == "loaded")
            command = [sys.executable, __file__, "_first", "--configuration", name, "--config", str(args.config),
                       "--dataset", str(args.dataset), "--manifest", str(args.manifest)] + (["--profile", str(args.profile)] if args.profile else [])
            begun = time.perf_counter()
            found = subprocess.run(command, capture_output=True, text=True, timeout=600)
            wall = time.perf_counter() - begun
            if found.returncode != 0:
                raise RuntimeError(f"first-search process failed for {name}: {found.stderr[-500:]}")
            runs.append({"configuration": name, "embedding_model": state, "process_wall_seconds": round(wall, 4), **json.loads(found.stdout)})
    set_embedding_model(settings, True)
    executable = Path(sys.executable).with_name("techdocqa.exe" if sys.platform == "win32" else "techdocqa")
    cli = []
    from techdocqa.evaluation.dataset import load_dataset
    query = load_dataset(args.dataset).questions[0].question
    for mode in ("bm25", "hybrid"):
        for _ in range(3):
            begun = time.perf_counter()
            found = subprocess.run([str(executable), "search", query, "--mode", mode, "--json", "--config", str(args.config)],
                                   capture_output=True, text=True, timeout=600)
            cli.append({"mode": mode, "wall_seconds": round(time.perf_counter() - begun, 4), "exit_code": found.returncode})
    return {"run_id": "latency_" + uuid.uuid4().hex, "kind": "cold", "procedure": PROCEDURE, "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": round(time.perf_counter() - started, 3),
            "scope": "evaluation", "runtime_before": before, "runtime_after": runtime(settings), "first_search": runs, "cli": cli}


def fmt(value) -> str:
    return "-" if value is None else f"{value:.3f}"


def render_markdown(report: dict) -> str:
    from techdocqa.evaluation.runtime import summary_line
    lines = [f"# Latency profile {report['run_id']} ({report['kind']})", "",
             f"- Date: {report['started_at']}, {report['duration_seconds']} s; procedure `{report['procedure']}` (P11-1)",
             f"- Code: {report['code']['commit']} (dirty: {report['code']['dirty']})"]
    if report.get("inventory"):
        hardware = report["inventory"]
        lines.append(f"- Hardware: {hardware.get('cpu')}, {hardware.get('cores')} cores / {hardware.get('threads')} threads, "
                     f"{(hardware.get('ram_total_bytes') or 0) / 2**30:.1f} GB RAM, GPUs: {', '.join(hardware.get('gpus') or []) or 'none'}; "
                     f"test processes running: {hardware.get('pytest_processes')}")
    lines += [summary_line(report["runtime_before"]).replace("- Runtime:", "- Runtime at start:"),
              summary_line(report["runtime_after"]).replace("- Runtime:", "- Runtime at end:")]
    if report["kind"] == "retrieval":
        lines += [f"- Scope: {report['scope']}" + (f" ({report['scope_sources']} sources)" if report["scope_sources"] else " (the whole local index)")
                  + f"; {report['dataset']['questions']} questions of `{report['dataset']['dataset_id']}`, {report['passes']} passes after one warm-up per configuration", "",
                  "| Configuration | Searches | Median (s) | p95 (s) | Max (s) | Target (s) | NFR-02 | Degraded | Changed rankings |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for row in report["configurations"]:
            stats = row["latency_seconds"]
            lines.append(f"| {row['configuration']} | {stats['n']} | {fmt(stats['median'])} | {fmt(stats['p95'])} | {fmt(stats['max'])} | "
                         f"{row['target_seconds']} | {'met' if row['met'] else 'NOT met'} | {row['degraded_searches']} | {row['changed_rankings']} |")
        for row in report["configurations"]:
            lines += ["", f"## Stages: {row['configuration']}", "",
                      "| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |", "|---|---|---|---|---|---|---|"]
            for name, stats in row["stages"].items():
                lines.append(f"| {name} | {stats['inside'] or '-'} | {stats['calls_per_query'] if stats['calls_per_query'] is not None else '-'} | "
                             f"{fmt(stats['mean'])} | {fmt(stats['median'])} | {fmt(stats['p95'])} | {stats['share_of_mean'] if stats['share_of_mean'] is not None else '-'} |")
    elif report["kind"] == "qa":
        stats = report["seconds"]
        lines += [f"- Mode: {report['mode']}, rerank {report['rerank']}; warm-up {report['warm_up']}",
                  f"- {report['dataset']['answerable']} answerable questions; {report['reached_generation']} reached generation, "
                  f"{report['timed_out']} timed out; statuses {report['statuses']}", "",
                  "| Over questions that reached generation | Median (s) | p95 (s) | Max (s) |", "|---|---|---|---|"]
        lines += [f"| {stage} | {fmt(stats[stage]['median'])} | {fmt(stats[stage]['p95'])} | {fmt(stats[stage]['max'])} |"
                  for stage in ("retrieval", "generation", "total")]
        refused = report["gate_refused"]
        lines += ["", f"NFR-03 (p95 at most {report['target_seconds']} s): **{'met' if report['met'] else 'NOT met'}**. "
                  f"Refused at the gate, no model call, not in the p95: {refused['questions']} "
                  f"(p95 {fmt(refused['total_seconds']['p95'])} s)."]
    else:
        lines += ["", "| Configuration | Embedding model | Process wall (s) | Imports (s) | Setup (s) | First search (s) | Second search (s) |",
                  "|---|---|---|---|---|---|---|"]
        lines += [f"| {row['configuration']} | {row['embedding_model']} | {fmt(row['process_wall_seconds'])} | {fmt(row['import_seconds'])} | "
                  f"{fmt(row['setup_seconds'])} | {fmt(row['first_seconds'])} | {fmt(row['second_seconds'])} |" for row in report["first_search"]]
        lines += ["", "| CLI `search` | Wall (s) | Exit |", "|---|---|---|"]
        lines += [f"| {row['mode']} | {fmt(row['wall_seconds'])} | {row['exit_code']} |" for row in report["cli"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=("retrieval", "cold", "qa", "_first"))
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "default.toml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "benchmark_full.jsonl")
    parser.add_argument("--manifest", type=Path, default=ROOT / "datasets" / "corpus_manifest.json")
    parser.add_argument("--scope", choices=("evaluation", "whole"), default="evaluation")
    parser.add_argument("--configuration", action="append", choices=tuple(TARGETS), help="repeat to choose; default all four")
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB, help="refuse to start below this much free RAM")
    parser.add_argument("--force", action="store_true", help="start even below --min-free-gb (the report records it)")
    args = parser.parse_args(argv)
    if args.kind == "_first":
        print(json.dumps(first_search(args)))
        return 0
    from techdocqa.evaluation.runner import code_version
    from techdocqa.evaluation.runtime import machine
    from techdocqa.registry import Registry
    from techdocqa.settings import load_settings
    settings = load_settings(args.config, args.profile)
    available = machine()["ram_available_bytes"]
    if available is not None and available < args.min_free_gb * 2**30 and not args.force:
        print(f"Only {available / 2**30:.2f} GB of RAM is free, below {args.min_free_gb} GB: close other apps or pass --force.", file=sys.stderr)
        return 3
    hardware = inventory()
    if hardware and hardware.get("pytest_processes"):
        print("A pytest process is running; latency would not be valid (P11-1).", file=sys.stderr)
        return 3
    if args.kind == "cold":
        report = cold_profile(args, settings)
    else:
        with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
            if args.kind == "retrieval":
                report = retrieval_profile(settings, registry, args.dataset, args.manifest, scope=args.scope,
                                           configurations=args.configuration, passes=args.passes)
            else:
                report = qa_profile(settings, registry, args.dataset, args.manifest)
    report.update(code=code_version(), inventory=hardware, forced_below_min_free=bool(args.force and available is not None
                                                                                      and available < args.min_free_gb * 2**30))
    directory = args.report_dir or Path(settings.data_directory) / "evaluation"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{report['run_id']}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (directory / f"{report['run_id']}.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"run_id": report["run_id"], "report_dir": str(directory)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
