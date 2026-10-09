"""Foundation CLI; ingestion, search and QA are not implemented yet."""

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from techdocqa import __version__
from techdocqa.schemas import ErrorDetail, ErrorResponse
from techdocqa.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="TechDocQA foundation utilities")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("config-check", help="validate settings without contacting providers")
    check.add_argument("--config", type=Path, default=Path("config/default.toml"))
    check.add_argument("--profile", type=Path)
    check.add_argument("--require-models", action="store_true")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config, args.profile)
        if args.require_models:
            settings.require_models()
    except (OSError, ValueError):
        # Do not echo validation inputs or exception strings: they may contain secrets.
        response = ErrorResponse(error=ErrorDetail(
            code="INVALID_CONFIGURATION",
            message="Configuration is unreadable, invalid, or missing required model selections.",
            stage="configuration",
            request_id=f"req_{uuid4().hex}",
        ))
        print(response.model_dump_json(), file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "configuration_valid",
        "framework": settings.framework,
        "provider": settings.model.provider,
        "model_selection_complete": bool(settings.model.chat_model and settings.model.embedding_model
                                         and settings.model.context_window),
        "provider_connection_checked": False,
    }))
    return 0
