"""Configuration, local registration and bounded online ingestion CLI."""

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
from techdocqa.schemas import ProcessingStatus, RegistrationMetadata
from techdocqa.settings import load_settings


class SafeArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        kwargs.setdefault("prog", "techdocqa")
        super().__init__(*args, **kwargs)

    def error(self, _message):
        # argparse's own message can contain every supplied argument and value.
        raise TechDocQAError("INVALID_ARGUMENT", "Invalid command or arguments. Use --help for accepted syntax.", stage="arguments")


def make_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description="TechDocQA configuration and documentation ingestion")
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
    for command in (check, ingest, status, listing, history, processing, chunking):
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
            }))
            return 0
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
                print(result.model_dump_json())
                return 1 if result.run.failed else 0
            if args.command == "process":
                from techdocqa.ingestion.processing import process_versions
                result = process_versions(args.version_ids, settings, registry)
                print(result.model_dump_json())
                return 1 if result.run.failed or result.warnings else 0
            if args.command == "ingest":
                if args.source or args.url:
                    from techdocqa.ingestion.online import ingest_online
                    result = ingest_online(args.source, args.url, settings, registry, metadata=metadata)
                else:
                    result = register_paths(args.paths, settings, registry, metadata=metadata, logical_name=args.logical_name)
                print(result.model_dump_json())
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
        print(error.response.model_dump_json(), file=sys.stderr)
        return 2 if error.response.error.code == "INVALID_ARGUMENT" else 1
