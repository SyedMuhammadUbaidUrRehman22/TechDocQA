"""Verify the frozen selection against the existing registry and processing APIs."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from techdocqa.ingestion.processing import finalized_documents
from techdocqa.registry import Registry
from techdocqa.settings import load_settings


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "datasets/corpus_manifest.json").read_text(encoding="utf-8"))
    settings = load_settings(root / "config/default.toml")
    reference = [item for item in manifest["documents"] if item["evaluation_included"]]
    assert 15 <= len(reference) <= 30
    assert 3 <= len({item["technology"] for item in reference}) <= 5
    counts = Counter(item["format"] for item in reference)
    assert counts["md"] >= 3 and counts["html"] >= 3 and counts["pdf"] >= 3 and counts["txt"] >= 1
    assert sum(item["size_bytes"] for item in manifest["documents"]) <= 50_000_000
    assert all(item["license_review"]["status"] == "verified" for item in reference)
    fingerprint_rows = [{key: item[key] for key in ("source_key", "raw_hash", "content_hash")} for item in reference]
    fingerprint = hashlib.sha256(json.dumps(fingerprint_rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert fingerprint == manifest["reference_fingerprint_sha256"]
    selected_urls = {item["source_url"] for item in reference if item["format"] == "html"}
    catalog_urls = {url for source in settings.online.sources if source.enabled for url in source.pages}
    assert selected_urls == catalog_urls
    raw_hashes, normalized_hashes = set(), set()
    with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
        current = {record.source_key: record for record in registry.list_documents()}
        for item in manifest["documents"]:
            record = current[item["source_key"]]
            assert record.source_key == item["source_key"]
            assert record.technology == item["technology"] and record.title == item["title"]
            assert record.license == item["license"] and record.source_url == item["source_url"]
            assert record.doc_type == item["format"] and record.size_bytes == item["size_bytes"]
            assert record.raw_hash == item["raw_hash"] and record.content_hash == item["content_hash"]
            assert record.finalized and record.is_active and record.status == "normalized"
            assert record.duplicate_of is None
            assert record.raw_hash not in raw_hashes and record.content_hash not in normalized_hashes
            raw_hashes.add(record.raw_hash)
            normalized_hashes.add(record.content_hash)
            source = root / item["local_path"]
            assert source.stat().st_size == item["size_bytes"]
            assert hashlib.sha256(source.read_bytes()).hexdigest() == record.raw_hash
            documents = finalized_documents(record.version_id, settings, registry)
            assert sum(len(doc.page_content.strip()) for doc in documents) >= 1000
            if record.doc_type == "pdf":
                assert source.read_bytes().startswith(b"%PDF-")
                assert len(documents) == record.page_count
                assert all(len(doc.page_content.strip()) > 100 for doc in documents)
                assert [doc.metadata["page"] for doc in documents] == list(range(1, len(documents) + 1))
    print(json.dumps({"verified_documents": len(manifest["documents"]),
                      "reference_documents": len(reference), "reference_formats": dict(counts),
                      "total_bytes": sum(item["size_bytes"] for item in manifest["documents"]),
                      "duplicate_documents": 0, "result": "passed"}))


if __name__ == "__main__":
    main()
