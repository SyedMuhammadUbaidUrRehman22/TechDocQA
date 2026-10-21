"""Isolated fetch/extraction worker; the parent imposes an overall deadline."""

from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import sys
import warnings

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.fetching import SafeFetcher
from techdocqa.settings import OnlineSettings, OnlineSource


def process_page(source: OnlineSource, url: str, policy: OnlineSettings,
                 max_bytes: int, minimum: int, directory: Path) -> dict:
    page = SafeFetcher(policy, max_bytes).fetch(url, source)
    (directory / "page.html").write_bytes(page.body)
    output = asdict(page)
    output.pop("body")
    try:
        from techdocqa.ingestion.html import extract_html
        output.update(extract_html(page.body, directory, minimum, page.content_type_header))
    except TechDocQAError as error:
        output["error"] = error.response.error.model_dump()
    return output


def main():
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        if os.environ.get("TECHDOCQA_OFFLINE") == "1":
            raise TechDocQAError("NETWORK_DISABLED", "Online ingestion is disabled in offline mode.", stage="fetch")
        request = json.loads(sys.stdin.buffer.read())
        output = process_page(OnlineSource.model_validate(request["source"]), request["url"],
                              OnlineSettings.model_validate(request["policy"]), request["max_bytes"],
                              request["minimum"], Path(request["directory"]))
    except TechDocQAError as error:
        output = {"error": error.response.error.model_dump()}
    except Exception:
        output = {"error": TechDocQAError("PAGE_PROCESSING_FAILED", "Documentation processing failed safely.", stage="extraction").response.error.model_dump()}
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
