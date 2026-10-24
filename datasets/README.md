# Reference corpus

Phase 4 update: the selected versions are now `chunked`; the frozen source hashes and evaluation selection remain unchanged. The public reference produces **1,609** chunks; private DDIA adds **3,934**. The verifier accepts later successful document stages. See [Phase 4](../docs/PHASE_4_STATUS.md) for the explicit CLI command, active chunk checks and model-input bound.

`corpus_manifest.json` freezes `techdocqa-reference-2026-10-24-v1`. It is a reviewed projection of the existing SQLite registry: source keys, IDs, source/normalized hashes, URLs, licenses, review limitations and relative paths. `config/default.toml` remains the approved HTML acquisition catalog. The manifest defines the evaluation selection; not every active registry document belongs to it.

The public reference contains **20 documents, 1,513,828 bytes, four technologies**: three Markdown, 13 HTML, three text-based PDF chapter excerpts and one TXT. The existing DDIA Markdown is an excluded **private supplement**, giving 21 local documents, 2,700,598 bytes and five domains. DDIA permissions and conversion fidelity are unverified. The public selection meets the numeric format/size/technology and public-source requirements without DDIA. Phase 4 measures 1,609 public-reference chunks.

All selected versions are normalized, finalized and active. The [corpus report](../docs/REFERENCE_CORPUS_STATUS.md) lists every source, review result, limitation and exact verification result. Review is by Codex; no second human review or benchmark approval is claimed.

## Storage and privacy

Manifest paths are relative to the repository root. `data/corpus` contains local Markdown/TXT/PDF inputs. HTML remains in Phase 3A's `data/online/snapshots`; processing artifacts remain in `data/processing`, with authoritative registry paths/hashes. `data/corpus-acquisition` retains the parent PDF and source/license/access-policy evidence. These stores are not alternate registries.

Existing `data/` and `.tmp/` exclusions cover the book, downloaded bodies, SQLite, snapshots and temporary render/test files. The manifest contains metadata and hashes only. Never upload DDIA to a provider or copy it into tracked directories. Retain upstream copyright/license/NOTICE obligations before any redistribution; this task did not authorize publication.

## Verify the frozen local selection

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\techdocqa.exe config-check
.\.venv\Scripts\techdocqa.exe list --json
.\.venv\Scripts\techdocqa.exe status --status chunked --json
.\.venv\Scripts\python.exe datasets/verify_corpus.py
```

The verifier uses existing `Registry` and `finalized_documents` APIs. It checks the frozen reference fingerprint, catalog selection, source bytes, registry metadata, finalized/active eligibility, unique raw/normalized hashes, immutable processing artifacts, usable text, PDF page coverage, format/domain counts and the 50,000,000-byte bound. It never prints book text or contacts a provider. Assertions must remain enabled: do not run Python with `-O`.

The registry also contains a processed Spark contents page rejected during review. `rejected_documents` records why it is excluded. Its registry state remains normalized/active; there is no CLI review-rejection or withdrawal command, so no undocumented state mutation was used. Evaluation must select `evaluation_included=true` manifest entries.

## Reproduce acquisition and registration

Preserve a private copy of the frozen `data/` directory for exact reproduction. HTML and `stable` URLs can change; hashes identify this snapshot. Changed upstream responses require a new reviewed corpus version. Source keys/hashes remain comparable after clean registration, although generated IDs can differ. Supply your own local DDIA copy to verify all 21 entries; these instructions never download DDIA.

The existing Phase 3A pipeline fetches exactly 13 catalog pages in four finite batches, each below the ten-page per-run limit:

```powershell
.\.venv\Scripts\techdocqa.exe ingest --source apache_kafka --category 'Distributed streaming' --version-label 4.3 --license Apache-2.0
.\.venv\Scripts\techdocqa.exe ingest --source apache_airflow --category 'Workflow orchestration' --version-label 'stable (version recorded in HTML title)' --license Apache-2.0
.\.venv\Scripts\techdocqa.exe ingest --source postgresql --category Databases --version-label 18 --license PostgreSQL
.\.venv\Scripts\techdocqa.exe ingest --source apache_spark --category 'Distributed computing' --version-label 4.0.1 --license Apache-2.0
```

Public-IP/TLS/scope/redirect/response/deadline controls are unchanged. The sites' robots policies allowed the selected pages at acquisition. No crawl or subresource download occurs; Redis and Docker remain disabled.

For local formats, retrieve only the three reference Markdown and one TXT `source_url` entries and save them to their manifest `local_path`. Verify their raw SHA-256 hashes before registration. Spark is pinned to tag `v4.0.1`; PostgreSQL TXT is pinned to commit `9412c35035a74b9e5623b4d7e67c5f77967f0d1a`. These are exact upstream text files, not output from a new HTML conversion adapter. Preserve Spark's original front matter/license headers and upstream LICENSE/NOTICE evidence referenced by `acquisition_evidence.resources`. Relative image and template references remain unrendered and are disclosed in review notes.

The three PDFs are **nonoverlapping tutorial chapters from one official PostgreSQL 18.6 manual**, not independently published manuals. Retrieve `https://www.postgresql.org/files/documentation/pdf/18/postgresql-18-A4.pdf` to `data/corpus-acquisition/postgresql-18-A4.pdf`: 15,864,875 bytes, SHA-256 `9c6af8d2c8f0eda1b05e510bd8028f752162d2f5ce2db405bbf197336ce638d2`. This preparation file is not selected as a fourth corpus PDF. The 3,156-page parent exceeds registration's limit; do not ingest it or raise the limit.

Reproduce excerpts with the already locked pypdf 6.21.1. Save the following under ignored `.tmp` and execute with `.venv\Scripts\python.exe`:

```python
import hashlib
import json
from pathlib import Path
from pypdf import PdfReader, PdfWriter

manifest = json.loads(Path('datasets/corpus_manifest.json').read_text(encoding='utf-8'))
for item in manifest['documents']:
    if item['format'] != 'pdf':
        continue
    preparation = item['preparation']
    parent = Path(preparation['parent_path'])
    assert hashlib.sha256(parent.read_bytes()).hexdigest() == preparation['parent_raw_hash']
    reader, writer = PdfReader(parent), PdfWriter()
    for page in preparation['original_physical_pages_1_based']:
        writer.add_page(reader.pages[page - 1], excluded_keys=('/Annots',))
    writer.add_metadata(preparation['pdf_metadata'])
    target = Path(item['local_path'])
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('wb') as handle:
            writer.write(handle)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == item['raw_hash']
```

Each prepends physical page 2 with the full legal notice. Body ranges are physical pages 42-45, 46-55 and 56-63 (printed pages 3-6, 7-16 and 17-24). Link annotations are omitted to avoid recursively cloning cross-manual references. Page text/resources/geometry are retained without reflow. `preparation` records metadata and maps excerpt citations to original physical pages.

Register the seven prepared local reference files through the existing CLI, using manifest metadata:

```powershell
$corpusManifest = Get-Content datasets/corpus_manifest.json -Raw | ConvertFrom-Json
foreach ($document in $corpusManifest.documents) {
    if (-not $document.evaluation_included -or $document.format -eq 'html') { continue }
    if ((Get-FileHash -LiteralPath $document.local_path -Algorithm SHA256).Hash -ne $document.raw_hash) {
        throw "Source differs from frozen manifest: $($document.local_path)"
    }
    .\.venv\Scripts\techdocqa.exe ingest $document.local_path --title $document.title --technology $document.technology --source-url $document.source_url --license $document.license --version-label $document.version_label --category $document.category
    if ($LASTEXITCODE -ne 0) { throw 'Registration failed' }
}
.\.venv\Scripts\techdocqa.exe process
.\.venv\Scripts\python.exe datasets/verify_corpus.py
```

First-time processing validates local files against registered bytes before immutable capture; later reruns verify snapshots offline. DDIA's original null license/category/version values remain unchanged in the registry. Review limitations live in the manifest, without rewriting registration history.

DS-05 fixtures remain separate and synthetic. Benchmark questions, second-person review, measured chunk counts, models, embeddings, indexes, retrieval and QA remain later work.
