# TechDocQA
TechDocQA is a domain-specific RAG project for answering software and data engineering questions from technical documentation with source citations. The planned system uses LangChain, semantic search, BM25 and NLP.

## Current status

Phase 3B adds deterministic normalization and transactional document-version finalization for local Markdown/HTML/TXT/PDF and Phase 3A's saved online extractions. `ingest` retains registration behavior; `process` completes the offline document layer. The catalog and secured online fetching remain intact. No splitting, indexing, retrieval or model calls are implemented. See [Phase 3B evidence and limits](docs/PHASE_3B_STATUS.md), [Phase 3A evidence](docs/PHASE_3A_STATUS.md) and [Phase 2 evidence](docs/PHASE_2_STATUS.md).

LangChain is approved. An open source model will be selected later; Ollama is the configured local serving profile and both chat/embedding model names remain unset. The original source still specifies OpenAI/Ollama portability, so OpenAI support remains a later requirement pending clarification if the project becomes local-only. No model weights or provider service are required for foundation tests.

## Reference corpus

The [2026-10-24 corpus report](docs/REFERENCE_CORPUS_STATUS.md) records 20 frozen public/openly licensed documents plus the existing private DDIA supplement: 21 documents, 2,700,598 bytes, five domains, four Markdown, 13 HTML, three text-based PDF excerpts and one TXT. Every selected version is normalized, finalized and active. The public selection meets the format/size/domain requirements without relying on DDIA's unverified permissions. See the [manifest](datasets/corpus_manifest.json) and [reproduction/verification instructions](datasets/README.md). Source material stays under ignored `data/`; the manifest contains provenance and hashes only.

## Setup

Use Python 3.11–3.13; Windows Python 3.13.3 is the verified development environment. From this repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\techdocqa.exe config-check
```

`config-check` validates settings without contacting providers. `config-check --require-models` intentionally fails while model names/context window are unset; it never verifies connectivity or model quality. TOML settings are in [config/default.toml](config/default.toml). TECHDOCQA_CHAT_MODEL and TECHDOCQA_EMBEDDING_MODEL override the model names; context_window must be selected in TOML. Relative paths resolve against the base configuration file.

Keep credentials out of TOML, logs and version control. Local runtime data and virtual environments are ignored. Phase 3A uses LangChain's pinned `BSHTMLLoader`, BeautifulSoup, urllib3 and certifi. The archived loader package is a documented maintenance limitation; its network client is never used. Vector, NLP and reranking integrations remain later work.

## Registration commands

Put permitted local files under `data/corpus`, or configure other allowed directories. Missing input roots are not created by registration. Blank roots are invalid. Paths outside the configured roots, including symlink/junction escapes, are rejected. The default limits are 20 MiB per file, 500 PDF pages and 60 seconds for PDF structural preflight.

```powershell
.\.venv\Scripts\techdocqa.exe ingest .\data\corpus\kafka.md --technology Kafka --version-label 3.9 --license Apache-2.0 --source-url https://example.org/docs --json
.\.venv\Scripts\techdocqa.exe ingest .\data\corpus --json
.\.venv\Scripts\techdocqa.exe list --json
.\.venv\Scripts\techdocqa.exe status --document-id doc_ID --json
.\.venv\Scripts\techdocqa.exe status --run-id run_ID --json
.\.venv\Scripts\techdocqa.exe status --status registered --json
.\.venv\Scripts\techdocqa.exe history doc_ID --json
```

Use IDs returned by `ingest`; `doc_ID`/`run_ID` illustrate their positions. Each command accepts `--config` and `--profile`, like `config-check`. Output is JSON by default; `--json` also works before the command. `ingest` accepts multiple paths and expands directories one level in sorted order. Every input has an outcome/index; nested/empty directories are explicit failures. A mixed batch preserves its successes and exits 1. Fatal errors are JSON on stderr; invalid CLI syntax exits 2 without echoing argument values. Success/help/version exit 0.

An unchanged source reuses its document/version IDs and increments the run's skipped count. Changed bytes reserve a linked **provisional** registration; `content_hash` stays null, `finalized` and `is_active` stay false until Phase 3 normalization. Equal filenames at different locations require an explicit `--logical-name` to avoid a source-key collision. Identical bytes under different names keep separate document IDs with a provisional `duplicate_of` link. Repeated metadata does not overwrite the original registration snapshot.

The registry is `data/registry.sqlite3` under the configured data directory. After a crashed registration, the next ingestion marks pending orphan attempts `RUN_INTERRUPTED` and safely reuses already committed registrations. Private paths are omitted from CLI records/errors; source URL credentials/query strings/fragments are removed before persistence. Licensing declarations are retained but not independently verified.

## Controlled online ingestion

The single source catalog is `[[online.sources]]` in [config/default.toml](config/default.toml). Kafka and Airflow are enabled; PostgreSQL, Spark, Redis and Docker are catalogued but disabled. There is no crawling, sitemap expansion, page-link discovery or JavaScript execution. Kafka's redirect-only entry is retained, while its default page is the explicitly configured official 4.3 introduction.

```powershell
.\.venv\Scripts\techdocqa.exe ingest --source apache_kafka --json
.\.venv\Scripts\techdocqa.exe ingest --source apache_airflow --json
.\.venv\Scripts\techdocqa.exe ingest --source apache_kafka --source apache_airflow --json
.\.venv\Scripts\techdocqa.exe ingest --url https://airflow.apache.org/docs/apache-airflow/stable/ --json
```

Repeat `--source` or `--url` for a finite batch (10 pages by default, configurable up to 20). Choose one selection mode per invocation; online technology/URL identity comes from the catalog, so do not combine online mode with local paths, `--logical-name`, `--technology` or `--source-url`. Existing title/category/version/license/language options still apply. `status`, `list` and `history` expose online provenance through the same registry. Partial batches exit 1 and retain successes.

Only enabled entry points and explicitly listed pages can be requested. Every redirect must remain in that source's declared HTTPS host/path scopes. The fetcher validates all DNS addresses, pins the connection to a public address with original-host TLS/SNI, rejects URL credentials/queries/ambiguous encoded paths and disables automatic redirects, proxies, decompression and library retries. It uses sequential requests, conservative pacing, bounded application retries, connection/read timeouts and an overall fetch/extraction deadline. See [network policy and limitations](docs/PHASE_3A_STATUS.md#network-and-storage-policy).

Raw HTML and whole-page extracted text live under ignored `data/online`; their byte/text hashes stay distinct. Code spans and heading paths retain structure. `ingest` registrations remain provisional until `process` runs. Repeated identical snapshots reuse IDs and preserve a fresh retrieval attempt; changed bytes create a linked candidate. Processing resolves normalized duplicates and finalizes changed content. The generated `data/online/corpus_manifest.json` is an unfrozen registry projection, not the reference corpus. Usage-policy references remain unverified and do not grant redistribution permission.

To add a source, add one TOML entry with a stable `source_id`, technology/title, HTTPS entry URL, explicit scopes and page list, and usage status/reference; set `enabled=true` after review. Activating an existing disabled source requires only that configuration change. No adapter change is needed. Custom configs must contain their own approved catalog. Keep `data_directory` private and on a filesystem supporting atomic hard-link snapshot publication.

The default suite blocks outbound sockets and sets `TECHDOCQA_OFFLINE=1` for workers. The optional live smoke is explicit:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests/test_online.py -m live --live --basetemp=.tmp/phase3a-live
```

Set `TECHDOCQA_OFFLINE=1` yourself to disable worker fetching outside tests. Live smoke snapshots are temporary ignored test data. No provider key, model or Ollama server is needed.

## Offline normalization and finalization

After local registration or an online fetch/extraction, process the returned provisional version ID, or omit IDs to process the latest candidate of every registered source:

```powershell
.\.venv\Scripts\techdocqa.exe process ver_ID --json
.\.venv\Scripts\techdocqa.exe process --json
```

`process` accepts the same `--config`/`--profile` flags and never fetches a URL or contacts a provider. Local sources must still match their registered bytes at first processing; afterward verified immutable snapshots support offline reruns. PDF parsing and normalization run inside a terminating worker using the configured deadline. Processing runs expose `stage=normalization` with the existing outcomes/results/errors and exit rules. Online manifest-export warnings exit 1 without discarding committed versions.

Prose uses LF, Unicode NFC and conservative whitespace cleanup. Headings, paragraphs, lists and Markdown hard breaks retain structure. Explicit HTML code, Markdown fences, inline backticks and indented code remain verbatim, including code Unicode and newlines. PDF page-edge boilerplate and vocabulary-supported line-break hyphenation use documented deterministic rules. See the complete [normalization/hash/version policy](docs/DECISIONS.md#phase-3b-normalization-and-finalization-2026-10-22).

`raw_hash` always hashes original bytes. `content_hash` hashes UTF-8 normalized text (ordered PDF pages joined by two LF characters); metadata is separate. Changed normalized text finalizes the new candidate and supersedes the previous active version atomically. Equivalent normalized text resolves to the existing finalized version; the byte candidate and its source provenance/history stay available without an extra finalized version. Different sources retain distinct identities and authoritative `duplicate_of` links. Failed processing retains the prior active version; the next run recovers interrupted attempts.

`status`/`list` still show the latest requested byte candidate, which can be failed or a nonfinalized duplicate. A duplicate's `processing.resolved_version_id` identifies its finalized content version; `history` exposes all candidates and active flags. `normalized` means eligible for later processing, not indexed/searchable. Finalized files remain private under `data/processing` and local byte snapshots under `data/local`; no document bodies enter SQLite. The schema and dependencies are unchanged. Older application readers cannot read the new metadata fields.

## Source and plan

The source filename says v2, but its contents identify **Revision 3**; those contents remain authoritative. The Phase 1 review records an existing local table-formatting edit; the requirement and acceptance-criterion text is unchanged.

- [Functional requirements](TechDocQA_Requirements_v2.md)
- [Traceability: all 24 FRs and 111 original acceptance criteria](docs/requirements_traceability.md)
- [Software Design Document](docs/TECHDOCQA_SDD.md)
- [Repository structure](docs/REPOSITORY_STRUCTURE.md)
- [Decisions and unresolved source questions](docs/DECISIONS.md)
- [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md)
- [Phase 1 checkpoint](docs/PHASE_1_STATUS.md)
- [Phase 2 plan and incomplete-work review](docs/PHASE_2_PLAN.md)
- [Phase 2 implementation checkpoint](docs/PHASE_2_STATUS.md)
- [Phase 3A plan and contract boundaries](docs/PHASE_3A_PLAN.md)
- [Phase 3A implementation checkpoint](docs/PHASE_3A_STATUS.md)
- [Phase 3B implementation checkpoint](docs/PHASE_3B_STATUS.md)
- [Development log](DEVELOPMENT_LOG.md)
- [LangChain loaders, corpus formats and metadata plan](docs/LANGCHAIN_INGESTION_PLAN.md)
- [Local development setup](deployment/local_setup.md)
- [Corpus preparation](datasets/README.md)

The reference corpus manifest remains draft with zero selected documents, so Phase 1 still has open gates. Online HTML smoke snapshots do not satisfy the 15–30 document, 3–5 technology, <=50 MB or Markdown/PDF/TXT format requirements. Next is Phase 4 segmentation/framework chunking. Hardware, budget, reviewer and model selection remain deferred.
