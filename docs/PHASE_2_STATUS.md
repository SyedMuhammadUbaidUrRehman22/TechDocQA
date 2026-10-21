# Phase 2 registration checkpoint

Verified 2026-10-21 on Windows with Python 3.13.3. Roadmap Phase 2 local registration and safety are implemented. This checkpoint completes the interrupted verification/documentation work; the implementation was already present in the working tree. It does not complete the remaining Phase 1 corpus gates or the later parsing, indexing and answering phases.

## Implemented behavior

- Reject blank/whitespace/NUL allowlist and storage paths. Resolve valid paths against the base TOML file; permit missing setup directories without creating input roots.
- Return section 8.4 JSON for malformed CLI arguments and configuration/domain failures, without echoing untrusted values. Preserve successful help, version and configuration checks.
- Persist documents, provisional byte registrations, runs, attempts and timestamped events in SQLite schema version 1. Enforce foreign keys, source/byte uniqueness, per-file transactions and safe schema mismatch/contention errors.
- Register `.md`, `.markdown`, `.html`, `.htm`, `.txt` and `.pdf` files independently. Read bounded actual bytes, calculate SHA-256, and reject unsupported/binary/archive/empty/missing/oversized inputs.
- Enforce allowed-directory containment against canonical paths and open file handles. Cover traversal, sibling prefixes, alternate drives, symlink/junction escapes, swapped roots and replacement before opening.
- Run PDF structure/encryption/page-count preflight in an isolated subprocess with a terminating deadline. This preflight does not extract text or establish that a PDF is text-based.
- Provide JSON `ingest`, `status`, `list` and `history`. Expand directories one level in deterministic order, preserve successful files in mixed batches, and report every input's indexed outcome and terminal run counts.
- Reuse IDs for an exact repeat, link changed byte candidates, require a logical name for equal-filename location collisions, and retain provisional byte-duplicate links across different sources.
- Recover orphaned runs after process death under an OS registration lock, preserving committed registrations and marking unresolved attempts `RUN_INTERRUPTED`. A live competing runner receives retryable `REGISTRY_BUSY`.
- Preserve source metadata and license declarations while removing source URL credentials/query strings/fragments and masking known secrets in metadata/failures. Keep private paths out of CLI records and document bodies out of SQLite.

The [implemented contracts](DECISIONS.md#implemented-phase-2-contracts-2026-10-21) define identity, lifecycle, retry and finalization boundaries. Every registered candidate still has `content_hash=null`, `finalized=false` and `is_active=false`. `processed` means successfully registered at the explicit `registration` stage. No extraction, normalization, searchable version or index is implied.

## Verification

Development environment:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip freeze --all --exclude techdocqa
.\.venv\Scripts\techdocqa.exe config-check
```

- Full offline suite: **85 passed in 20.72 seconds**, with no skips. Windows case identity, file symlinks and directory junctions were exercised.
- `pip check`: **No broken requirements found.** All **49** nonproject installed packages, including pip/build/test tools, match `requirements.lock.txt` exactly.
- Installed console entry point: configuration valid, model selection incomplete and provider connectivity explicitly unchecked.
- CLI subprocess tests execute ingestion, document/run/status queries, listing, history and repeated registration through new processes. Mixed batches exit 1 and retain successful results in JSON stdout; invalid syntax exits 2 with JSON stderr. Help/version exit 0.
- Real worker/process tests terminate a slow PDF subprocess and abruptly exit a registration process, then verify bounded failure and restart recovery. Permission failure and replacement-before-open are controlled fault injections, not claims of an OS permissions audit.

Fresh installation verification used a new, initially empty environment:

```powershell
.\.venv\Scripts\python.exe -m venv .venv-phase2-resume-verify
.\.venv-phase2-resume-verify\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv-phase2-resume-verify\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv-phase2-resume-verify\Scripts\python.exe -m pytest
.\.venv-phase2-resume-verify\Scripts\python.exe -m pip check
.\.venv-phase2-resume-verify\Scripts\python.exe -m pip freeze --all --exclude techdocqa
.\.venv-phase2-resume-verify\Scripts\techdocqa.exe config-check
```

Installation and editable-package build succeeded. The fresh environment passed **85 tests in 22.53 seconds**, with no skips; `pip check` passed, all **49** locked packages matched exactly, and the installed CLI returned the same configuration-only result. Both complete test runs used synthetic local inputs without provider calls.

Documentation checks resolved **61 local Markdown links** and found no replacement characters in 13 documents. `git diff --check` passed when excluding the preserved requirements edit; the full check flags that existing edit's trailing space on line 62. No requirements formatting was changed during this continuation.

The only dependency added by Phase 2 is `pypdf==6.21.1`, used for PDF metadata preflight. Framework loader/splitter integrations, vector stores, NLP packages and model weights were not added. The [LangChain loading and metadata plan](LANGCHAIN_INGESTION_PLAN.md) records their later integration boundaries.

## Acceptance evidence and boundaries

| Requirement / slice | Executed evidence | Remaining boundary |
|---|---|---|
| FR-01, AC-01.1–01.5 | `test_ingest.py`: distinct registrations for four formats; unsupported format listing; false PDF; missing input; 2-valid/1-invalid directory. `test_safety.py`: actual byte limit. | Local registration acceptance only; optional URL ingestion remains later work. |
| FR-02, AC-02.1/02.2 | `test_ingest.py` and `test_registry.py`: required registration fields, hashes, UTC timestamps, null/default optional fields, metadata and restart persistence. A framework `Document` can carry the persisted metadata. | Format-derived title AC-02.4, chunk ownership AC-02.3 and vector projection AC-02.5 remain Phases 3–5. |
| FR-05 foundation | `test_registry.py`: unchanged IDs, changed provisional candidates, failed retry, same-byte different sources, filename collision and Windows aliases. | No normalized deduplication, finalized-version, supersession or index-count acceptance claim. |
| FR-20, AC-20.1–20.3 registration slice | `test_ingest.py`: 5-valid/2-invalid counts; `test_registry.py`/`test_cli.py`: run/status/history across restarts; `test_safety.py`: URL-secret masking before persistence. | Complete processing history and indexed rerun AC-20.4 remain later. |
| FR-22, AC-22.2 and registration CLI slices | `test_cli.py`: standard argument/configuration errors, generated sensitive markers, exit codes, help/version and cross-process operations. | Search, ask, withdraw, delete, evaluation and provider-switch demonstration are unimplemented. No complete FR-22 claim. |
| FR-23, AC-23.1/23.2 local slice | `test_safety.py`: byte/page bounds, encrypted/malformed PDF, real deadline, containment, open-handle race, symlink/junction/root replacement and fail-closed allowlist. | Full extraction timeout, configured-model injection AC-23.3 and full-system secret scan AC-23.4 remain later. URL AC-23.5 is optional P2. |
| DS-05 registration fixtures | Generated synthetic duplicate, modified, differently named, image-only PDF, unsupported-format and Latin-1 inputs in `conftest.py`/registration tests. | These are not corpus documents or evidence of parser/normalization correctness. |

Status and history tests live in `test_registry.py` and `test_cli.py`; a separate planned `test_status.py` was unnecessary. All **24 FR headings and 111 original acceptance-criterion lines** match the traceability source records verbatim. The user's existing requirements table-formatting edit is preserved. Its SHA-256 remains `D458DDB2175D507004806738D3F87DE41405D40D39676B52995E07DB3D479949`.

## Remaining work

The corpus manifest is still draft with zero documents. Phase 1 needs 15–30 permitted documents across 3–5 technologies, the required format mix, source/license evidence and byte hashes; hardware, budget and a second evaluation reviewer remain open. Registration does not independently verify licensing.

Next is Phase 3 framework loading, source snapshot/revalidation, extraction, code-preserving normalization and authoritative content hashes/finalized version decisions. Resolve Q-10/Q-11 preservation/encoding details using the [loader plan](LANGCHAIN_INGESTION_PLAN.md) and [roadmap](IMPLEMENTATION_ROADMAP.md#phase-3--parsing-normalization-and-versioning). Model selection remains deferred to Phases 5/7.

No provider call, model download, extraction, benchmark, quality/performance measurement or remote publication was performed for this checkpoint. Python 3.11/3.12 and non-Windows environments remain unverified. Linux has a `/proc/self/fd` handle-check implementation but no result is claimed here; other platforms fail closed.
