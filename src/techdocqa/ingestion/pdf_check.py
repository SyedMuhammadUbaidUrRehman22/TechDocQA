"""Isolated PDF page-count preflight. Never extract text or execute PDF actions."""

from io import BytesIO
import json
import logging
import sys

from pypdf import PdfReader


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        reader = PdfReader(BytesIO(sys.stdin.buffer.read()), strict=True)
        if reader.is_encrypted:
            print(json.dumps({"error": "PDF_ENCRYPTED"}))
        else:
            print(json.dumps({"pages": len(reader.pages)}))
    except Exception:
        # The parent receives no parser diagnostics or original document data.
        print(json.dumps({"error": "INVALID_PDF"}))


if __name__ == "__main__":
    main()
