# Phase 3A controlled online ingestion checkpoint

Historical Phase 3A evidence follows. Update 2026-10-22: [Phase 3B](PHASE_3B_STATUS.md) now adds local framework loading, offline normalization of the saved online extraction, and finalized-version handling. `ingest` still registers provisional candidates; `process` performs the new step. Statements below about absent normalization describe Phase 3A alone. Catalog, fetch security, immutable raw/extracted snapshots and original regression tests are preserved.

Completed and verified 2026-10-21 on Windows/Python 3.13.3. TechDocQA can fetch explicitly selected official Kafka/Airflow pages, extract whole-page text through LangChain, retain snapshots/provenance and register provisional URL candidates in the existing SQLite registry. This is not a complete RAG pipeline or the remaining Phase 3 local parsing/normalization work.

The [inspection plan and conflicts](PHASE_3A_PLAN.md) preceded implementation. [Online decisions](DECISIONS.md#phase-3a-online-contracts-2026-10-21) preserve Phase 2 local identities, provisional eligibility and the existing errors. URL ingestion remains optional P2 in the unchanged authoritative requirements; the user explicitly selected this limited slice early.

## Architecture and changed files

TOML approved catalog -> explicit page selection -> isolated worker with validated HTTPS fetch -> LangChain local HTML loading/structure adapter -> immutable raw/extracted snapshots -> existing registry runs/attempts/versions -> JSON CLI and derived runtime manifest.

| Files | Purpose |
|---|---|
| `config/default.toml`, `src/techdocqa/settings.py` | One catalog, activation/scope validation and bounded network settings using existing TOML/Pydantic conventions. |
| `ingestion/urls.py` | Canonical HTTPS syntax and host/path scope checks, with no network access. |
| `ingestion/fetching.py` | Public DNS validation, IP-pinned TLS fetches, bounded responses, manual redirects/retries and pacing. |
| `ingestion/html.py` | LangChain BSHTMLLoader around cleaned local HTML; preserve technical/code text, heading paths and code offsets. |
| `ingestion/online_worker.py` | Isolate fetch/extraction; emit only structured metadata/errors. Parent deadline terminates slow work, including DNS. |
| `ingestion/online.py` | Finite selection, worker coordination, snapshot integrity/storage, existing registry coordination and manifest export. |
| `src/techdocqa/schemas.py`, `registry.py` | Optional online provenance in existing JSON columns; normalized URL identity for online records. No SQL migration or registry rewrite. |
| `src/techdocqa/cli.py` | Add online selection to existing `ingest`; preserve local operations/JSON error conventions. |
| `datasets/corpus_manifest.json`, `datasets/README.md` | Reference the generated unfrozen candidate projection and preserve actual course corpus requirements. |
| `tests/test_online.py`, `tests/conftest.py` | Mocked network/security/extraction/lifecycle/CLI tests, global offline denial and explicitly enabled live tests. Original 85 Phase 2 tests remain in the full suite. |
| `pyproject.toml`, `requirements.lock.txt` | Required loader/parser/network dependencies, live marker and exact compatible lock. |
| `README.md`, setup/roadmap/loader plan/decisions/SDD/structure/traceability, Phase 3A plan/status and development log | Commands, contracts, source activation, limits, evidence and remaining gates. |

The ingestion paths above are under `src/techdocqa/ingestion`. No provider, embeddings, vector database, BM25, reranking, QA, browser UI or public deployment was added.

## Approved catalog and commands

| Source ID | Official entry | Default selection / activation |
|---|---|---|
| `apache_kafka` | `https://kafka.apache.org/documentation/` | Enabled; one explicit `https://kafka.apache.org/43/getting-started/introduction/` page. |
| `apache_airflow` | `https://airflow.apache.org/docs/apache-airflow/stable/` | Enabled; entry page only. |
| `postgresql` | `https://www.postgresql.org/docs/current/` | Catalogued, disabled. |
| `apache_spark` | `https://spark.apache.org/docs/latest/` | Catalogued, disabled. |
| `redis` | `https://redis.io/docs/latest/` | Catalogued, disabled. |
| `docker` | `https://docs.docker.com/` | Catalogued, disabled. |

Kafka's supplied entry currently serves a client-side redirect rather than useful body text. Its configured default explicitly selects the official introduction; the application does not discover this URL dynamically or execute that redirect. Requesting the entry directly remains allowed but may fail extraction. The other sources require review/activation in TOML. Apache license-page references are recorded as **unverified usage-policy references**, not document redistribution grants; unknown policy references are null.

```powershell
.\.venv\Scripts\techdocqa.exe ingest --source apache_kafka --json
.\.venv\Scripts\techdocqa.exe ingest --source apache_airflow --json
.\.venv\Scripts\techdocqa.exe ingest --source apache_kafka --source apache_airflow --json
.\.venv\Scripts\techdocqa.exe ingest --url https://airflow.apache.org/docs/apache-airflow/stable/ --json
.\.venv\Scripts\techdocqa.exe status --run-id <returned-run-id> --json
.\.venv\Scripts\techdocqa.exe status --document-id <returned-document-id> --json
.\.venv\Scripts\techdocqa.exe history <returned-document-id> --json
```

Choose local paths, repeated `--source`, or repeated `--url`, exclusively. Online URL/technology identity comes from the catalog; `--logical-name`, `--technology` and `--source-url` overrides are rejected in online mode. Existing title/category/version/license/language flags remain available. Only enabled catalog entries and finite configured pages can be initial URLs. A bad page/source in a batch does not discard the others.

Online output retains `run`/`outcomes`, adding page counts, relative manifest path and warnings. Per-attempt `online` metadata includes source ID, normalized requested URL, final response URL, retrieval ID/UTC time, MIME/original content-type header, HTTP cache metadata, original title, encoding, raw snapshot identity/path, extracted hash/path, extraction policy/dependency versions/configuration hash, heading paths/code spans, extraction state/warnings and usage status. Unavailable metadata remains null. `normalized_hash` and registry `content_hash` remain null.

No new CLI command family was introduced. Existing `status`, `list`, `history`, help/version and configuration-check behavior remains. Exit codes remain 0 success/help/version, 1 domain/partial-batch failure, 2 invalid syntax. A manifest export warning also exits 1 while retaining committed successes.

To add a source, add a `[[online.sources]]` entry with stable ID, technology/title, HTTPS entry, explicit scopes and finite pages, activation and usage status/reference. Activating a listed source only changes `enabled`; the PostgreSQL test demonstrates this without adapter changes. Configurations are operator-controlled approvals. Custom configuration files contain their own catalog.

## Network and storage policy

- HTTPS/port 443 only; reject URL credentials, query parameters, whitespace/control characters, encoded/ambiguous paths and unsupported schemes. Fragments are removed from identity. Host/path matching uses segment boundaries and exact hosts.
- Validate every initial/hop/retry URL. Resolve all DNS answers and reject mixed public/private answers, loopback, private, link-local, shared/reserved/multicast and IPv4-mapped/transition addresses. Connect to a validated numeric IP with the original hostname retained for TLS certificate verification, SNI and Host. DNS rebinding cannot substitute a new hostname resolution at connection time.
- urllib3 automatic redirects/retries are disabled. Environment proxies, cookies and authentication are not used. Requests are sequential, with one registry runner under the existing OS lock; default per-host interval is 1 second. Separate independently configured registries do not coordinate global host pacing.
- Default connection/read timeouts are 5/10 seconds; at most 2 retries and 3 redirects. Short `Retry-After` is respected; a delay over 10 seconds returns a retryable error rather than retrying early. DNS failures remain safe retryable results. The overall worker deadline uses the existing 60-second parse setting and terminates stalled DNS, response reading or extraction.
- Responses must be HTTP 200 HTML/XHTML. Reject other types/statuses, compressed responses and invalid lengths. Request identity encoding and cap actual entity-body bytes at the existing 20 MiB limit, including responses without a declared length. `raw_hash` hashes these fetched entity bytes, not the URL, extracted text or an entire HTTP wire exchange.
- No link following, recursive crawling, sitemap requests, JavaScript rendering, OCR, subresource fetches or HTML canonical-tag identity changes. Dynamic-only pages or scopes that have drifted may fail safely; update the explicit catalog after review.
- LangChain loads a cleaned local representation. Remove scripts/styles/navigation/header/footer/aside/forms/controls and recognizable cookie/banner elements. Keep whole-page body text, lists/table text, hierarchy and exact decoded code/identifiers; record half-open code offsets into extracted text. Strictly honor declared HTTP charset or record detected encoding. Missing/malformed titles warn and leave original title null, with a catalog display fallback. Cleaning is heuristic, not a claim of perfect boilerplate removal.
- Raw HTML and UTF-8 extracted text are content-addressed separately under `<data_directory>/online/{snapshots,extracted}`. Complete files are fsynced then published with an atomic hard link; existing bytes are verified and never overwritten. Paths in metadata/manifests are relative to the data directory. The directory is trusted private local storage and requires hard-link support (tested on this Windows filesystem), not a hostile multi-user filesystem boundary. Unreferenced complete files after interruption are retained; no automatic evidence deletion was added.
- Errors use static sanitized project messages; URL credentials/queries/bodies and dependency diagnostics are not emitted. Worker logs/warnings are suppressed; explicit extraction warnings remain metadata. Setting `TECHDOCQA_OFFLINE=1` disables worker fetching.

## Registry, snapshots and manifest

Schema/application IDs, all SQL tables/constraints, per-file transactions and Phase 2 local filename/logical-name identities remain unchanged. Online source keys use the normalized requested URL; `final_url` records redirects without silently changing requested identity. Neither URL alone nor downloaded filename identifies content.

The optional registry API context persists in existing `metadata_json`/`result_json`. A successful byte registration remains `registered`, provisional, inactive and unsearchable. Exact raw repeats reuse document/version IDs, preserve immutable first-registration metadata and record a fresh retrieval attempt; changed bytes reserve a predecessor-linked candidate and preserve history. Different raw HTML that might later normalize equally is still provisional; no normalized deduplication or supersession is claimed.

Failed fetches retain attempts/errors with unknown fields null. A failed extraction retains its completed raw snapshot and extraction failure on the attempt, without fabricating a successful document/version. Complete local FR-03 failure-state/finalization semantics remain later work. New code reads prior Phase 2 databases; older readers do not understand online JSON fields, so downgrading after online ingestion is unsupported. No SQL migration runner was present or added.

The committed reference manifest remains draft with zero selected documents. It points to the runtime `online/corpus_manifest.json` projection, generated atomically from registry versions/attempts using the existing manifest shape. It includes all online provisional versions and per-retrieval outcomes with actual hashes/paths/status. It is not another registry or a frozen evaluation corpus. `export_manifest(registry, data_root)` can regenerate the projection; callers should hold the registration lock. Export failure does not roll back a committed registration and is reported with `MANIFEST_EXPORT_FAILED`.

## Executed verification

| Check | Actual result |
|---|---|
| Development full suite before the final two charset tests | **158 passed, 2 skipped**, 1 deprecation warning, 24.47 seconds. |
| Final full offline suite in a new clean installation | **160 passed, 2 skipped, 0 failed**, 1 deprecation warning, 33.28 seconds. Includes all original 85 Phase 2 tests and 75 new offline cases. |
| Final optional live smoke after charset handling | **2 passed, 75 deselected, 0 failed**, 1 deprecation warning, 6.64 seconds. Both official Kafka/Airflow pages fetched and extracted. |
| Fresh virtualenv, exact lock and editable package installation | Passed using `.venv-phase3a-verify`. |
| `pip check` and exact installed inventory | Passed; all **67** nonproject packages match the lock in the clean environment. |
| Installed `techdocqa.exe config-check` | Passed; model selection remains incomplete and connectivity unchecked. |
| `pip wheel --no-deps --no-build-isolation` | Passed; normal installable wheel built. |
| Documentation and source preservation | 78 local links resolve across 15 documents; all 24 FR headings and 111 AC lines still match verbatim. Requirements SHA-256 remains `D458DDB2175D507004806738D3F87DE41405D40D39676B52995E07DB3D479949`. |
| `git diff --check` | Full check exits 2 solely for the user's pre-existing requirements-table trailing space at line 62, preserved intentionally. Excluding that unchanged source edit passes; all new files also pass whitespace checks. |
| Lint/type-check commands | None configured in this project; no invented lint/type result. |

The two default skips are precisely the opt-in live cases. Offline tests patch DNS/socket connection entry points and force worker offline mode; mocked transports exercise fetch/extraction without a server, provider or internet. Live tests explicitly clear that mode and use their own ignored temporary registries/snapshots. They did not populate/freeze the reference corpus.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests/test_online.py -m live --live --basetemp=.tmp/phase3a-live-final
.\.venv-phase3a-verify\Scripts\python.exe -m pytest --basetemp=.tmp/phase3a-clean-tests
.\.venv-phase3a-verify\Scripts\python.exe -m pip check
.\.venv-phase3a-verify\Scripts\python.exe -m pip freeze --all --exclude techdocqa
.\.venv-phase3a-verify\Scripts\python.exe -m pip wheel --no-deps --no-build-isolation --wheel-dir .tmp/phase3a-dist .
```

Offline coverage includes successful Kafka/Airflow, catalog-only PostgreSQL activation, unapproved paths/hosts, unsafe syntax/credentials/schemes, nonpublic/mixed DNS, redirect scope and rebinding, TLS/DNS failures, redirect limits, declared/actual oversize, content type/encoding/length errors, 404/429/5xx/timeouts/retry exhaustion/Retry-After, malformed/insufficient HTML, title warnings, code/tokens/heading/table provenance, declared charset, exact repeats/changed candidates/history/reopen, partial/invalid source batches, CLI/config JSON, no discovery, real worker termination, offline worker denial, corrupt snapshots, storage escapes and manifest failure isolation.

## Dependencies and remaining gates

New direct declarations: `langchain-community>=0.4.2,<0.5`, `beautifulsoup4>=4.15,<5`, `urllib3>=2.8,<3`, and `certifi>=2026.7.22`. The lock pins 0.4.2, 4.15.0, 2.8.0 and 2026.7.22 respectively. urllib3/certifi were already installed/pinned; declaring them directly reflects their new direct use. The loader brings 18 additional packages in total, including required classic/text-splitter dependencies; no splitters, ORM or model pipeline is invoked. No model weights or unrelated provider integrations were installed. A pin comparison verified that all 49 original Phase 2 package versions remain retained.

`langchain-community` emits an upstream sunset warning and its repository is archived ([official notice](https://github.com/langchain-ai/langchain-community/issues/674)). The pinned BSHTMLLoader matches the approved framework direction and uses maintained BeautifulSoup underneath, but selecting a maintained standalone replacement remains technical debt before broader deployment. Only Windows/Python 3.13.3 installation/network/storage behavior was executed; other supported Python versions/platforms are unverified.

DS-01–DS-04 still need a reviewed/frozen **15–30 actual documents**, **3–5 technologies**, **<=50 MB**, **>=3 Markdown, >=3 HTML, >=3 text PDFs and >=1 TXT**, source/license evidence and normalized hashes. Online URLs do not replace real local format coverage. The approximate 3,000-chunk target is not measured. Hardware/budget/reviewer, models/provider portability, benchmark, latency/cost and answer quality remain open.

Before chunking: complete local framework loading, code-safe normalization and authoritative finalized-version handling; preserve the raw/extracted artifacts and offsets created here. Then implement approved segmentation/framework splitting, embeddings/index lifecycle, retrieval, calibrated answering/citations and evaluation in their existing roadmap phases. No corpus download publication, Git push or deployment was performed.
