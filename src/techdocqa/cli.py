"""Command-line interface: configuration, ingestion, processing, enrichment, search, answers, lifecycle and evaluation."""

import argparse
import json
from pathlib import Path
import sys
from typing import get_args

from pydantic import ValidationError

from techdocqa import __version__
from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.pipeline import register_paths
from techdocqa.registry import Registry
from techdocqa.schemas import ProcessingStatus, RegistrationMetadata, SearchFilters, SearchRequest
from techdocqa.settings import load_settings


class SafeArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        kwargs.setdefault("prog", "techdocqa")
        super().__init__(*args, **kwargs)

    def error(self, _message):
        # argparse's own message can contain every supplied argument and value.
        raise TechDocQAError("INVALID_ARGUMENT", "Invalid command or arguments. Use --help for accepted syntax.", stage="arguments")


def emit(result, *, file=None) -> None:
    # ASCII escapes keep JSON printable on any console or pipe encoding (Windows defaults to a legacy code page).
    print(json.dumps(result.model_dump(), ensure_ascii=True), file=file or sys.stdout)


def print_text(text: str) -> None:
    # Characters the console's code page cannot show become "?" instead of crashing the command.
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))


def render_answer(response) -> str:
    """FR-22.2: the status, the answer and the numbered citations with their sources."""
    from techdocqa.answering.generation import FAILURES
    lines = [f"Status: {response.status}" + (f" ({response.reason})" if response.reason else "")]
    if response.status == "generation_error":
        lines += ["", FAILURES.get(response.reason, ("A required provider or index failed; the reason code names it.",))[0]]
    elif response.answer:
        lines += ["", response.answer]
    gate = response.sufficiency
    if response.reason == "LOW_RELEVANCE" and gate is not None and gate.components:
        judged = "; ".join(f"{name} best {check.top_score}, needs {check.min_top_score}" for name, check in gate.components.items())
        lines += [f"Hybrid gate '{gate.gate}': {judged} (calibration run {gate.calibration_run_id})."]
    elif response.reason == "LOW_RELEVANCE" and gate is not None:
        lines += [f"Best match relevance {gate.top_score}; this mode needs {gate.min_top_score} "
                  f"(calibration run {gate.calibration_run_id})."]
    codes = {warning.code for warning in response.warnings}
    if response.degraded:
        scale = (gate.thresholds_from if gate else None) or response.mode
        lines += ["", f"Warning: search was degraded ({response.degradation_reason}); the answer used the results that remained, "
                      f"judged by the {scale} thresholds."]
    if codes & {"SUFFICIENCY_NOT_CALIBRATED", "SUFFICIENCY_CALIBRATION_STALE"}:
        lines += ["", "Warning: no calibrated relevance threshold applies to this retrieval mode, so this answer was not gated "
                      "and questions the documents do not cover may still be answered."]
    shown = response.citations or response.context_consulted
    if shown:
        lines += ["", "Citations:" if response.citations else "Context consulted (the answer's citations could not be verified):"]
        for citation in shown:
            where = " > ".join(part for part in (citation.title, citation.section_path) if part) or citation.source
            page = f", page {citation.page}" if citation.page is not None else ""
            lines += [f"  [{citation.label}] {where}{page}", f"       {citation.source_url or citation.source}"]
    lines += ["", f"Chunks used: {response.chunks_used} of {response.chunks_retrieved}; "
                  f"{response.latency_ms.total} ms; model {response.model_id}"]
    return "\n".join(lines)


def answer_configuration(args) -> dict:
    """An answer run's search mode and rerank switch; hybrid+rerank is hybrid reranked, otherwise reranking follows
    the configuration."""
    if not args.mode:
        return {"mode": None, "rerank": None}
    return {"mode": "hybrid", "rerank": True} if args.mode[0] == "hybrid+rerank" else {"mode": args.mode[0], "rerank": None}


def calibration_status(settings) -> dict:
    """Per mode, whether its FR-18 thresholds apply to the configured score scale (AC-18.5); no provider is contacted."""
    from techdocqa.answering.sufficiency import STALE, active_thresholds
    from techdocqa.indexing.embeddings import embedding_profile
    status = {}
    for mode in ("bm25", "vector", "hybrid"):
        try:
            thresholds, warning = active_thresholds(mode, settings, embedding_profile(settings.model) if mode != "bm25" else None)
        except TechDocQAError:
            # No verified embedding profile means no vector scale to calibrate against.
            thresholds, warning = None, None
        status[mode] = "calibrated" if thresholds else ("stale" if warning == STALE else "not_calibrated")
    return status


def make_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description="TechDocQA: technical documentation search and question answering")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--json", action="store_true", help="emit JSON (also the default)")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("config-check", help="validate settings without contacting providers")
    check.add_argument("--require-models", action="store_true")
    ingest = commands.add_parser("ingest", help="register local files or fetch/extract explicit approved HTML pages")
    ingest.add_argument("paths", type=Path, nargs="*", help="files or directories, expanded one level")
    online_selector = ingest.add_mutually_exclusive_group()
    online_selector.add_argument("--source", action="append", default=[], help="enabled catalog source ID; repeat for a finite batch")
    online_selector.add_argument("--url", action="append", default=[], help="explicit catalog-approved page; repeat for a finite batch")
    ingest.add_argument("--logical-name", help="disambiguate equal filenames at different locations")
    for field in RegistrationMetadata.model_fields:
        ingest.add_argument("--" + field.replace("_", "-"), default=None)
    status = commands.add_parser("status", help="query a document, run, or processing status")
    selector = status.add_mutually_exclusive_group(required=True)
    selector.add_argument("--document-id")
    selector.add_argument("--run-id")
    selector.add_argument("--status", choices=get_args(ProcessingStatus))
    listing = commands.add_parser("list", help="list the latest registration of each source")
    listing.add_argument("--status", choices=get_args(ProcessingStatus))
    history = commands.add_parser("history", help="show a source's byte registrations and event history")
    history.add_argument("document_id")
    processing = commands.add_parser("process", help="offline normalization/finalization of registered versions (default: latest candidates)")
    processing.add_argument("version_ids", nargs="*")
    chunking = commands.add_parser("chunk", help="offline segmentation/chunking of active finalized nonduplicate versions")
    chunking.add_argument("version_ids", nargs="*")
    indexing = commands.add_parser("index", help="embed active chunks and update the vector index; unchanged chunks make no model call")
    indexing.add_argument("version_ids", nargs="*")
    indexing.add_argument("--rebuild", action="store_true", help="restore the whole vector index from stored embeddings")
    enriching = commands.add_parser("enrich", help="extract entities, keyphrases and categories from active chunks; "
                                                   "unchanged documents are skipped")
    enriching.add_argument("version_ids", nargs="*")
    showing = commands.add_parser("enrichment", help="show a document's entities, keyphrases and categories (read-only)")
    showing.add_argument("document_id")
    showing.add_argument("--chunk-id", help="only this current chunk's entities and keyphrases")
    searching = commands.add_parser("search", help="search active chunks by BM25 or vector similarity")
    searching.add_argument("query", help="query text; put -- first if it begins with a dash")
    searching.add_argument("--mode", choices=["bm25", "vector", "hybrid"])
    searching.add_argument("--top-k", type=int)
    searching.add_argument("--rerank", action=argparse.BooleanOptionalAction, help="rerank the candidates (default: configuration)")
    for field in SearchFilters.model_fields:
        searching.add_argument("--" + field.replace("_", "-"))
    asking = commands.add_parser("ask", help="answer a question from active chunks, citing them; refuses without a model call "
                                             "when no chunk meets the calibrated relevance threshold")
    asking.add_argument("question", help="question text, 1 to 1000 characters; put -- first if it begins with a dash")
    asking.add_argument("--mode", choices=["bm25", "vector", "hybrid"])
    asking.add_argument("--rerank", action=argparse.BooleanOptionalAction, help="rerank the candidates (default: configuration)")
    for field in SearchFilters.model_fields:
        asking.add_argument("--" + field.replace("_", "-"))
    asking.add_argument("--retrieval-config-id", help="answer only if this is the active retrieval configuration")
    asking.add_argument("--text", action="store_true", help="print the answer, numbered citations and status as text instead of JSON")
    withdrawal = commands.add_parser("withdraw", help="remove a document from search immediately; re-ingesting reactivates it")
    withdrawal.add_argument("document_id")
    withdrawal.add_argument("--reason", required=True)
    deletion = commands.add_parser("delete", help="permanently remove a document, its versions, chunks, embeddings and index entries")
    deletion.add_argument("document_id")
    deletion.add_argument("--reason", required=True)
    deletion.add_argument("--yes", action="store_true", help="confirm this cannot be undone")
    evaluation = commands.add_parser("eval", help="run a benchmark: Precision, Recall and nDCG at 1/3/5 and MRR per configuration, "
                                                  "paired differences, and proposed refusal thresholds")
    evaluation.add_argument("--dataset", type=Path, default=Path("datasets/benchmark_smoke.jsonl"))
    evaluation.add_argument("--manifest", type=Path, default=Path("datasets/corpus_manifest.json"),
                            help="frozen corpus manifest; only its evaluation documents are searched")
    evaluation.add_argument("--mode", action="append", choices=["bm25", "vector", "hybrid", "hybrid+rerank"],
                            help="configuration; repeat to choose; default bm25 and vector")
    evaluation.add_argument("--report-dir", type=Path, help="where the JSON and Markdown reports go (default: <data>/evaluation)")
    answer_runs = evaluation.add_mutually_exclusive_group()
    answer_runs.add_argument("--answers", type=int, metavar="N",
                             help="instead of retrieval metrics, answer N answerable questions with the configured model for human review")
    answer_runs.add_argument("--refusal", action="store_true",
                             help="instead of retrieval metrics, ask every question with the configured model and report AC-18.1/18.2")
    answer_runs.add_argument("--record-review", type=Path, metavar="SHEET",
                             help="copy the ratings from a filled answer review sheet into its report and judge AC-16.6")
    answer_runs.add_argument("--enrichment", action="store_true",
                             help="instead of retrieval metrics, score Phase 9 enrichment against the frozen gold sets, propose the "
                                  "unclassified threshold and check the enriched corpus (read-only)")
    evaluation.add_argument("--reviewer", help="who rated the answers, recorded with --record-review")
    evaluation.add_argument("--gold-dir", type=Path, default=Path("datasets/nlp"),
                            help="frozen Phase 9 gold sets and out-of-topic fixtures, read by --enrichment")
    evaluation.add_argument("--fixtures", type=Path,
                            help="out-of-topic fixtures for --enrichment (default: out_of_topic.jsonl in --gold-dir)")
    for command in (check, ingest, status, listing, history, processing, chunking, indexing, enriching, showing, searching, asking,
                    withdrawal, deletion, evaluation):
        command.add_argument("--config", type=Path, default=Path("config/default.toml"))
        command.add_argument("--profile", type=Path)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                             help="emit JSON (also the default)")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = make_parser().parse_args(argv)
        if args.command == "ingest":
            online = bool(args.source or args.url)
            if bool(args.paths) == online or (online and (args.logical_name is not None or args.technology is not None or args.source_url is not None)):
                raise TechDocQAError("INVALID_ARGUMENT", "Choose local paths or one online selection mode; online identity comes from the catalog.", stage="arguments")
        if args.command == "eval" and args.answers is not None and (args.answers < 1 or len(args.mode or []) > 1):
            raise TechDocQAError("INVALID_ARGUMENT", "--answers needs a positive count and at most one --mode.", stage="arguments")
        if args.command == "eval" and args.refusal and len(args.mode or []) > 1:
            raise TechDocQAError("INVALID_ARGUMENT", "--refusal takes at most one --mode.", stage="arguments")
        if args.command == "eval" and args.enrichment and args.mode:
            raise TechDocQAError("INVALID_ARGUMENT", "--enrichment measures enrichment, not a retrieval mode.", stage="arguments")
        try:
            settings = load_settings(args.config, args.profile)
            if args.command == "config-check" and args.require_models:
                settings.require_models()
        except (OSError, ValueError, RuntimeError):
            raise TechDocQAError(
                "INVALID_CONFIGURATION",
                "Configuration is unreadable, invalid, or missing required model selections.",
                stage="configuration",
            ) from None
        if args.command == "config-check":
            print(json.dumps({
                "status": "configuration_valid", "framework": settings.framework,
                "provider": settings.model.provider,
                "model_selection_complete": bool(settings.model.chat_model and settings.model.embedding_model
                                                 and settings.model.context_window),
                "provider_connection_checked": False,
                "sufficiency": calibration_status(settings),
            }))
            return 0
        if args.command == "delete" and not args.yes:
            raise TechDocQAError("CONFIRMATION_REQUIRED", "Deletion cannot be undone; repeat with --yes to confirm.", stage="arguments")
        if args.command == "eval" and args.record_review is not None:
            # Files only: no registry, index or model is touched.
            from techdocqa.evaluation.answers import record_review
            report, files = record_review(args.record_review, args.report_dir or Path(settings.data_directory) / "evaluation",
                                          args.reviewer)
            print(json.dumps({"run_id": report["run_id"], "ac_16_6": report["summary"]["ac_16_6"], "report_files": files},
                             ensure_ascii=True))
            return 0
        request = None
        if args.command == "search":
            try:
                request = SearchRequest(query=args.query, mode=args.mode or settings.retrieval.mode,
                    top_k=settings.retrieval.top_k if args.top_k is None else args.top_k,
                    rerank=settings.retrieval.rerank if args.rerank is None else args.rerank,
                    filters=SearchFilters(**{field: getattr(args, field) for field in SearchFilters.model_fields}))
            except ValidationError:
                raise TechDocQAError("INVALID_ARGUMENT", "Query must be 1 to 1000 characters and top-k positive.", stage="arguments") from None
        metadata = None
        if args.command == "ingest":
            try:
                metadata = RegistrationMetadata(**{
                    field: getattr(args, field) for field in RegistrationMetadata.model_fields
                    if getattr(args, field) is not None
                })
            except ValidationError:
                raise TechDocQAError("INVALID_METADATA", "Registration metadata is invalid.", stage="arguments") from None
        with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
            if args.command == "chunk":
                from techdocqa.ingestion.chunks import chunk_versions
                result = chunk_versions(args.version_ids, settings, registry)
                emit(result)
                return 1 if result.run.failed else 0
            if args.command == "index":
                from techdocqa.indexing.pipeline import index_versions
                result = index_versions(args.version_ids, settings, registry, rebuild=args.rebuild)
                emit(result)
                return 1 if result.run.failed else 0
            if args.command == "enrich":
                from techdocqa.enrichment.pipeline import enrich_versions
                result = enrich_versions(args.version_ids, settings, registry)
                emit(result)
                return 1 if result.run.failed else 0
            if args.command == "enrichment":
                from techdocqa.enrichment.pipeline import show_enrichment
                print(json.dumps(show_enrichment(args.document_id, settings, registry, args.chunk_id), ensure_ascii=True))
                return 0
            if args.command == "search":
                from techdocqa.retrieval.search import search
                emit(search(request, settings, registry))
                return 0
            if args.command == "ask":
                from techdocqa.answering.generation import answer_question
                response = answer_question(args.question, settings, registry, mode=args.mode,
                    filters=SearchFilters(**{field: getattr(args, field) for field in SearchFilters.model_fields}),
                    expected_config_id=args.retrieval_config_id, rerank=args.rerank)
                if args.text:
                    print_text(render_answer(response))
                else:
                    emit(response)
                return 1 if response.status == "generation_error" else 0
            if args.command == "eval" and args.answers is not None:
                from techdocqa.evaluation.answers import run_answer_review, write_answer_report
                report, texts = run_answer_review(args.dataset, args.manifest, settings, registry, count=args.answers,
                                                  **answer_configuration(args))
                # Cited chunk text stays in the ignored data directory, wherever the report goes.
                files = write_answer_report(report, args.report_dir or Path(settings.data_directory) / "evaluation",
                                            Path(settings.data_directory) / "evaluation", texts)
                output = {key: value for key, value in report.items() if key != "questions"}
                print(json.dumps({**output, "report_files": files}, ensure_ascii=True))
                return 1 if report["summary"]["statuses"]["generation_error"] else 0
            if args.command == "eval" and args.enrichment:
                from techdocqa.evaluation.enrichment import run_enrichment_evaluation, summary as enrichment_summary
                from techdocqa.evaluation.enrichment import write_enrichment_report
                report = run_enrichment_evaluation(args.manifest, args.gold_dir, settings, registry, args.fixtures)
                files = write_enrichment_report(report, args.report_dir or Path(settings.data_directory) / "evaluation")
                print(json.dumps({**enrichment_summary(report), "report_files": files}, ensure_ascii=True))
                return 1 if report["classification"].get("status") == "failed" else 0
            if args.command == "eval" and args.refusal:
                from techdocqa.evaluation.answers import run_refusal_check, write_refusal_report
                report = run_refusal_check(args.dataset, args.manifest, settings, registry, **answer_configuration(args))
                files = write_refusal_report(report, args.report_dir or Path(settings.data_directory) / "evaluation")
                output = {key: value for key, value in report.items() if key != "questions"}
                print(json.dumps({**output, "report_files": files}, ensure_ascii=True))
                return 1 if report["summary"]["statuses"]["generation_error"] else 0
            if args.command == "eval":
                from techdocqa.evaluation.runner import run_evaluation, summary, write_report
                report = run_evaluation(args.dataset, args.manifest, settings, registry, modes=args.mode)
                files = write_report(report, args.report_dir or Path(settings.data_directory) / "evaluation")
                print(json.dumps({**summary(report), "report_files": files}, ensure_ascii=True))
                return 0 if all(row["status"] == "completed" for row in report["configurations"]) else 1
            if args.command == "withdraw":
                from techdocqa.indexing.lifecycle import withdraw_document
                emit(withdraw_document(args.document_id, args.reason, registry))
                return 0
            if args.command == "delete":
                from techdocqa.indexing.lifecycle import delete_document
                result = delete_document(args.document_id, args.reason, settings, registry)
                emit(result)
                return 1 if result.warnings else 0
            if args.command == "process":
                from techdocqa.ingestion.processing import process_versions
                result = process_versions(args.version_ids, settings, registry)
                emit(result)
                return 1 if result.run.failed or result.warnings else 0
            if args.command == "ingest":
                if args.source or args.url:
                    from techdocqa.ingestion.online import ingest_online
                    result = ingest_online(args.source, args.url, settings, registry, metadata=metadata)
                else:
                    result = register_paths(args.paths, settings, registry, metadata=metadata, logical_name=args.logical_name)
                emit(result)
                return 1 if result.run.failed or getattr(result, "warnings", []) else 0
            if args.command == "status" and args.run_id is not None:
                output = registry.get_run(args.run_id).model_dump()
            elif args.command == "status" and args.document_id is not None:
                record = registry.get_document(args.document_id)
                output = {"document": record.model_dump(), "history": registry.history(args.document_id)["events"]}
            elif args.command == "history":
                output = registry.history(args.document_id)
            else:
                output = {"documents": [record.model_dump() for record in registry.list_documents(args.status)]}
        print(json.dumps(output, ensure_ascii=True))
        return 0
    except TechDocQAError as error:
        emit(error.response, file=sys.stderr)
        return 2 if error.response.error.code == "INVALID_ARGUMENT" else 1
