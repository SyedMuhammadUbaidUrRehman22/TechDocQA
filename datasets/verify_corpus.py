"""Verify the frozen selection against the existing registry and processing APIs."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from techdocqa.ingestion.processing import finalized_documents
from techdocqa.ingestion.chunks import active_chunks
from techdocqa.registry import Registry
from techdocqa.settings import load_settings


def check(condition, message):
    # Not assert: these are the verifier's results and must also run under python -O.
    if not condition:
        raise SystemExit(json.dumps({"result": "failed", "check": message}))


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "datasets/corpus_manifest.json").read_text(encoding="utf-8"))
    settings = load_settings(root / "config/default.toml")
    reference = [item for item in manifest["documents"] if item["evaluation_included"]]
    check(15 <= len(reference) <= 30, "reference document count")
    check(3 <= len({item["technology"] for item in reference}) <= 5, "reference technology count")
    counts = Counter(item["format"] for item in reference)
    check(counts["md"] >= 3 and counts["html"] >= 3 and counts["pdf"] >= 3 and counts["txt"] >= 1, "reference format counts")
    check(sum(item["size_bytes"] for item in manifest["documents"]) <= 50_000_000, "corpus size")
    check(all(item["license_review"]["status"] == "verified" for item in reference), "license review")
    fingerprint_rows = [{key: item[key] for key in ("source_key", "raw_hash", "content_hash")} for item in reference]
    fingerprint = hashlib.sha256(json.dumps(fingerprint_rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    check(fingerprint == manifest["reference_fingerprint_sha256"], "reference fingerprint")
    selected_urls = {item["source_url"] for item in reference if item["format"] == "html"}
    catalog_urls = {url for source in settings.online.sources if source.enabled for url in source.pages}
    check(selected_urls == catalog_urls, "catalog pages match the selection")
    raw_hashes, normalized_hashes, chunk_counts = set(), set(), {}
    with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
        current = {record.source_key: record for record in registry.list_documents()}
        for item in manifest["documents"]:
            key = item["source_key"]
            check(key in current, f"{key}: registered")
            record = current[key]
            check(record.technology == item["technology"] and record.title == item["title"], f"{key}: technology and title")
            check(record.license == item["license"] and record.source_url == item["source_url"], f"{key}: license and URL")
            check(record.doc_type == item["format"] and record.size_bytes == item["size_bytes"], f"{key}: format and size")
            check(record.raw_hash == item["raw_hash"] and record.content_hash == item["content_hash"], f"{key}: hashes")
            check(record.finalized and record.is_active and record.status in {"normalized", "chunked", "embedded", "indexed"}, f"{key}: eligibility")
            check(record.duplicate_of is None, f"{key}: not a duplicate")
            check(record.raw_hash not in raw_hashes and record.content_hash not in normalized_hashes, f"{key}: unique content")
            raw_hashes.add(record.raw_hash)
            normalized_hashes.add(record.content_hash)
            source = root / item["local_path"]
            check(source.stat().st_size == item["size_bytes"], f"{key}: file size")
            check(hashlib.sha256(source.read_bytes()).hexdigest() == record.raw_hash, f"{key}: file hash")
            documents = finalized_documents(record.version_id, settings, registry)
            if record.chunking:
                chunks = active_chunks(record.version_id, settings, registry)
                check(len(chunks) == record.chunking.chunk_count, f"{key}: chunk count")
                chunk_counts[record.source_key] = len(chunks)
            check(sum(len(doc.page_content.strip()) for doc in documents) >= 1000, f"{key}: usable text")
            if record.doc_type == "pdf":
                check(source.read_bytes().startswith(b"%PDF-"), f"{key}: PDF signature")
                check(len(documents) == record.page_count, f"{key}: page count")
                check(all(len(doc.page_content.strip()) > 100 for doc in documents), f"{key}: page text")
                check([doc.metadata["page"] for doc in documents] == list(range(1, len(documents) + 1)), f"{key}: page numbers")
    print(json.dumps({"verified_documents": len(manifest["documents"]),
                      "reference_documents": len(reference), "reference_formats": dict(counts),
                      "total_bytes": sum(item["size_bytes"] for item in manifest["documents"]),
                      "verified_chunks": sum(chunk_counts.values()),
                      "reference_chunks": sum(chunk_counts.get(item['source_key'], 0) for item in reference),
                      "duplicate_documents": 0, "result": "passed"}))


if __name__ == "__main__":
    sys.exit(main())
