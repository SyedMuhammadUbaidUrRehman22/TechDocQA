"""Offline local loading and normalization; parent terminates work at the deadline."""

import json
import logging
from pathlib import Path
import sys
import warnings

from langchain_core.documents import Document

from techdocqa.errors import TechDocQAError
from techdocqa.normalization import document_text, normalize_documents


def process(request: dict) -> dict:
    directory = Path(request["directory"])
    if request.get("chunking"):
        from techdocqa.chunking import build_chunks
        from techdocqa.settings import ChunkingSettings, ModelSettings
        documents = [Document(**item) for item in json.loads((directory / "input.json").read_text(encoding="utf-8"))]
        result = build_chunks(documents, ChunkingSettings.model_validate(request['chunking']),
                              model=ModelSettings.model_validate(request.get('model', {})))
        (directory / 'chunks.json').write_bytes(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8'))
        return {'chunk_count': len(result['chunks'])}
    if request.get("extracted"):
        documents = [Document(**item) for item in json.loads((directory / "input.json").read_text(encoding="utf-8"))]
    else:
        from techdocqa.ingestion.loaders import load_documents
        try:
            documents = load_documents(Path(request["snapshot"]), request["doc_type"], directory, request["minimum"])
        except TechDocQAError:
            raise
        except Exception:
            raise TechDocQAError("EXTRACTION_FAILED", "Local document extraction failed safely.", stage="extraction") from None
    (directory / "extracted.json").write_text(json.dumps([
        {"page_content": doc.page_content, "metadata": doc.metadata} for doc in documents
    ], ensure_ascii=True, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    normalized = normalize_documents(documents, minimum=request["minimum"])
    (directory / "normalized.json").write_text(json.dumps([
        {"page_content": doc.page_content, "metadata": doc.metadata} for doc in normalized
    ], ensure_ascii=True, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    (directory / "normalized.txt").write_bytes(document_text(normalized).encode("utf-8"))
    metadata = documents[0].metadata
    return {key: metadata.get(key) for key in ("original_title", "encoding", "extraction_dependencies")}


def main():
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    # This worker only consumes private snapshots. Deny accidental loader/provider network use.
    import socket
    def denied(*args, **kwargs):
        raise OSError("Network is disabled in the processing worker")
    socket.getaddrinfo = socket.socket.connect = socket.socket.connect_ex = denied
    request = {}
    try:
        request = json.loads(sys.stdin.buffer.read())
        output = process(request)
    except TechDocQAError as error:
        output = {"error": error.response.error.model_dump()}
    except Exception:
        stage = 'chunking' if isinstance(request, dict) and request.get('chunking') else 'normalization'
        output = {"error": TechDocQAError("PROCESSING_FAILED", "Document processing failed safely.", stage=stage).response.error.model_dump()}
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
