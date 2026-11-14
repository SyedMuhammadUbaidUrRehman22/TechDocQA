"""Phase 11 ingestion timing (P11-4, NFR-04): the frozen corpus from an empty registry, in a scratch data directory.

Usage: python scripts/time_ingestion.py [--scope reference|all] [--scratch DIR] [--keep] [--report-dir DIR]

Copies of the frozen bytes (each manifest entry's snapshot, HTML included) are registered with their manifest
metadata, then processed, chunked, indexed and enriched, each stage timed on its own through the same functions the
CLI commands call. The embedding cache starts empty, and every embedding request is counted, so the run cannot be a
cache hit. Each normalized content_hash is compared with the manifest, and differences are reported, not fixed.
`--scope all` adds the private supplement (NFR-01 headroom, P11-3).

Nothing is written to the repository's data/ directory. The scratch directory is deleted afterwards unless --keep.
Reports hold counts, hashes' equality and timings only, never document text; by default they go to <data>/evaluation.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
TARGET_SECONDS = 30 * 60  # NFR-04 with local embeddings on the reference machine


class CountingEmbeddings:
    """Passes every call to the real embedder and counts what it is asked to embed."""

    def __init__(self, inner):
        self.inner, self.requests, self.texts = inner, 0, 0

    def embed_documents(self, texts):
        self.requests += 1
        self.texts += len(texts)
        return self.inner.embed_documents(texts)

    def embed_query(self, text):
        self.requests += 1
        self.texts += 1
        return self.inner.embed_query(text)


def release_chroma() -> None:
    """Chroma keeps every client system open for the life of the process; stop them so the scratch files can go."""
    shared = sys.modules.get("chromadb.api.shared_system_client")
    if shared is None:
        return
    systems = list(shared.SharedSystemClient._identifier_to_system.values())
    shared.SharedSystemClient.clear_system_cache()
    for system in systems:
        try:
            system.stop()
        except Exception:
            pass


def scratch_settings(base: Path, scratch: Path, profile: Path | None):
    from techdocqa.settings import load_settings
    settings = load_settings(base, profile)
    corpus, data = scratch / "corpus", scratch / "data"
    enrichment = settings.enrichment.model_copy(update={"gazetteer": str((base.parent / settings.enrichment.gazetteer).resolve())
                                                        if not Path(settings.enrichment.gazetteer).is_absolute() else settings.enrichment.gazetteer})
    return settings.model_copy(update={"allowed_directories": [str(corpus)], "data_directory": str(data), "enrichment": enrichment})


def time_ingestion(settings, manifest_path: Path, scratch: Path, *, scope: str = "reference", enrich: bool = True) -> dict:
    """settings must already point at scratch/corpus and scratch/data (scratch_settings)."""
    from techdocqa.enrichment.pipeline import enrich_versions
    from techdocqa.evaluation.runtime import runtime
    from techdocqa.indexing import embeddings
    from techdocqa.indexing.pipeline import index_versions
    from techdocqa.ingestion.chunks import chunk_versions
    from techdocqa.ingestion.pipeline import register_paths
    from techdocqa.ingestion.processing import process_versions
    from techdocqa.registry import Registry
    from techdocqa.schemas import RegistrationMetadata
    if scope not in ("reference", "all"):
        raise ValueError(f"unknown scope {scope!r}")
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / "corpus").mkdir(parents=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = [item for item in manifest["documents"] if scope == "all" or item["evaluation_included"]]
    files = []
    for number, item in enumerate(documents, 1):
        source = ROOT / item["snapshot_path"]
        target = scratch / "corpus" / f"{number:02d}-{Path(item['snapshot_path']).name}"
        shutil.copyfile(source, target)
        files.append((item, target))
    started_at = datetime.now(timezone.utc).isoformat()
    before = runtime(settings)
    real_build = embeddings.build_embeddings
    counters = []

    def counted(value):
        counter = CountingEmbeddings(real_build(value))
        counters.append(counter)
        return counter

    stages, versions = {}, {}
    embeddings.build_embeddings = counted
    try:
        with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
            assert registry.eligible_versions() == [], "the scratch registry must start empty"
            began = time.perf_counter()
            for item, path in files:
                metadata = RegistrationMetadata(technology=item.get("technology"), category=item.get("category"),
                                                version_label=item.get("version_label"), license=item.get("license"))
                outcome = register_paths([path], settings, registry, metadata=metadata).outcomes[0]
                versions[path.name] = (item, outcome.result.version_id)
            stages["ingest"] = time.perf_counter() - began
            began = time.perf_counter()
            processed = process_versions([version for _, version in versions.values()], settings, registry)
            stages["process"] = time.perf_counter() - began
            finalized = {}
            for outcome in processed.outcomes:
                finalized[outcome.result.version_id] = outcome.result
            began = time.perf_counter()
            chunked = chunk_versions([], settings, registry)
            stages["chunk"] = time.perf_counter() - began
            began = time.perf_counter()
            indexed = index_versions([], settings, registry)
            stages["index"] = time.perf_counter() - began
            # Counted before enrich, which embeds its own category descriptions.
            embedded = {"requests": sum(counter.requests for counter in counters), "texts": sum(counter.texts for counter in counters),
                        "providers_built": len(counters), "batch_size": settings.model.embedding_batch_size}
            enriched = None
            if enrich:
                began = time.perf_counter()
                enriched = enrich_versions([], settings, registry)
                stages["enrich"] = time.perf_counter() - began
            records = registry.eligible_versions()
            from techdocqa.ingestion.chunks import stored_chunks
            chunk_count = sum(len(stored_chunks(record, settings)) for record in records)
            distinct = len({chunk["text_hash"] for record in records for chunk in stored_chunks(record, settings)})
            by_hash = {record.content_hash: record for record in records}
            matches = [{"format": item["format"], "evaluation_included": item["evaluation_included"],
                        "content_hash_equal": item["content_hash"] in by_hash} for item, _ in versions.values()]
            statuses = sorted({record.status for record in records})
            failures = {"process": processed.run.failed, "chunk": chunked.run.failed, "index": indexed.run.failed,
                        "enrich": getattr(getattr(enriched, "run", None), "failed", None)}
    finally:
        embeddings.build_embeddings = real_build
        release_chroma()
    searchable = sum(stages[name] for name in ("ingest", "process", "chunk", "index"))
    return {"run_id": "ingestion_" + uuid.uuid4().hex, "kind": "ingestion", "scope": scope, "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "documents": len(files), "formats": {name: sum(1 for item, _ in files if item["format"] == name) for name in ("html", "md", "pdf", "txt")},
            "bytes": sum(path.stat().st_size for _, path in files),
            "stages_seconds": {name: round(value, 3) for name, value in stages.items()},
            "to_searchable_seconds": round(searchable, 3),
            "with_enrich_seconds": round(searchable + stages["enrich"], 3) if "enrich" in stages else None,
            "target_seconds": TARGET_SECONDS, "met": searchable <= TARGET_SECONDS,
            "chunks": chunk_count, "distinct_chunk_texts": distinct, "eligible_versions": len(records), "statuses": statuses,
            "embedding": embedded, "cache_miss_proved": embedded["texts"] == distinct > 0,
            "content_hash_matches": sum(1 for item in matches if item["content_hash_equal"]),
            "content_hash_differences": [item for item in matches if not item["content_hash_equal"]],
            "failures": failures, "runtime_before": before, "runtime_after": runtime(settings)}


def render_markdown(report: dict) -> str:
    from techdocqa.evaluation.runtime import summary_line
    stages = report["stages_seconds"]
    lines = [f"# Ingestion timing {report['run_id']} ({report['scope']})", "",
             f"- Date: {report['started_at']}; code {report['code']['commit']} (dirty: {report['code']['dirty']})",
             summary_line(report["runtime_before"]).replace("- Runtime:", "- Runtime at start:"),
             summary_line(report["runtime_after"]).replace("- Runtime:", "- Runtime at end:"),
             f"- {report['documents']} documents ({', '.join(f'{count} {name}' for name, count in report['formats'].items())}), "
             f"{report['bytes']:,} bytes; {report['chunks']} chunks, {report['distinct_chunk_texts']} distinct texts",
             f"- Embedding: {report['embedding']['texts']} texts in {report['embedding']['requests']} requests from an empty cache "
             f"(cache miss proved: {report['cache_miss_proved']})",
             f"- Content hashes equal to the manifest: {report['content_hash_matches']} of {report['documents']}; failures {report['failures']}", "",
             "| Stage | Seconds |", "|---|---|", *[f"| {name} | {value:.1f} |" for name, value in stages.items()],
             f"| **To searchable (ingest to index)** | **{report['to_searchable_seconds']:.1f}** |",
             f"| With enrich | {report['with_enrich_seconds'] if report['with_enrich_seconds'] is not None else '-'} |", "",
             f"NFR-04 (at most {report['target_seconds'] // 60} min with local embeddings): **{'met' if report['met'] else 'NOT met'}**."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "default.toml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--manifest", type=Path, default=ROOT / "datasets" / "corpus_manifest.json")
    parser.add_argument("--scope", choices=("reference", "all"), default="reference")
    parser.add_argument("--scratch", type=Path, default=ROOT / ".tmp" / "p11-ingest")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args(argv)
    from techdocqa.evaluation.runner import code_version
    from techdocqa.settings import load_settings
    scratch = args.scratch.resolve()
    if scratch == ROOT / "data" or ROOT / "data" in scratch.parents:
        print("The scratch directory must not be inside data/.", file=sys.stderr)
        return 2
    try:
        report = time_ingestion(scratch_settings(args.config, scratch, args.profile), args.manifest, scratch, scope=args.scope)
    finally:
        if not args.keep and scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
    report["code"] = code_version()
    directory = args.report_dir or Path(load_settings(args.config, args.profile).data_directory) / "evaluation"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{report['run_id']}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (directory / f"{report['run_id']}.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"run_id": report["run_id"], "report_dir": str(directory), "to_searchable_seconds": report["to_searchable_seconds"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
