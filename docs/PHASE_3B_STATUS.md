# Phase 3B content normalization and document-version finalization

Implementation checkpoint 2026-10-22, Windows/Python 3.13.3. The remaining roadmap Phase 3 work is implemented: local framework extraction, deterministic code-preserving normalization, immutable normalized artifacts and transactional version finalization. Phase 3A controlled fetching/extraction and the existing registration CLI remain intact. The roadmap originally had no separately named 3B phase; this work follows its Phase 3 parsing/normalization/versioning responsibilities. Phase 4 remains segmentation/framework chunking.

## Implemented behavior

`ingest` retains local registration and controlled online extraction. New `process [version_ids ...]` uses the existing registry runs/attempts; without IDs it processes each source's latest byte candidate. It is entirely offline. Online input uses verified Phase 3A raw/extracted snapshots without fetching or extracting HTML again. Local Markdown/HTML/TXT/PDF is handle-validated against the registered raw hash, captured immutably and loaded with the installed LangChain loaders in a terminating worker. Future consumers can read verified framework Documents with `finalized_documents(resolved_version_id, settings, registry)`.

The complete [normalization, hashing, identity and lifecycle contract](DECISIONS.md#phase-3b-normalization-and-finalization-2026-10-22) is authoritative for this implementation. Prose normalizes CRLF/CR to LF, uses Unicode NFC and conservative whitespace cleanup. Markdown hierarchy, paragraph boundaries, lists and hard breaks remain structured. Code spans/fences/inline backticks and indentation remain verbatim, including their original Unicode/newlines. PDF page numbers and repeated page-edge boilerplate use explicit rules, and line-break hyphenation joins only words supported by document prose vocabulary while protecting paths/flags. Invalid text/spans and insufficient usable content fail structurally.

`raw_hash` stays SHA-256 of original bytes. Authoritative `content_hash` is SHA-256 of normalized texts in source-page order joined by two LF characters, encoded as UTF-8 without a BOM or an added terminal newline. Metadata is separate; page boundaries and code-internal newlines remain part of this exact representation. Original extraction JSON, normalized text and normalized Documents JSON have their own immutable artifacts/hashes; Phase 3A's original extracted-text hash retains its meaning. No chunk hash or chunks are introduced.

Distinct normalized content finalizes its provisional ID and atomically supersedes the previous active row. Equivalent content resolves to an existing finalized version while retaining the separate byte candidate, source snapshot and attempt/provenance history. Such candidates remain nonfinalized/inactive, with their normalized hash and `resolved_version_id` in processing metadata. Distinct logical sources retain their own document/version identity and authoritative `duplicate_of`. Metadata-only repeats preserve the first metadata. Returning to old content never restores a superseded version. Failed candidates leave the prior finalized version active; orphan recovery, OS locking and SQL transactions protect retries and concurrent work.

`status`/`list` continue to show the latest requested byte candidate, which can differ from the active finalized version. Processing results return the resolved finalized version ID. `history` and `get_version` retain all candidates and eligibility flags. Normalized/finalized does not mean indexed or searchable. Future indexing must check active eligibility and skip authoritative `duplicate_of` sources by default.

## Files changed

| Files | Change |
|---|---|
| `src/techdocqa/normalization.py` | Deterministic normalization, protected code offsets, headings, PDF edge cleanup and canonical text representation. |
| `src/techdocqa/ingestion/loaders.py`, `processing_worker.py`, `processing.py` | Local framework loading, bounded offline worker, verified immutable artifacts, batch coordination and finalized Document reads. |
| `src/techdocqa/registry.py`, `schemas.py` | Processing provenance, legacy-row reading, attempt binding, transactional finalization/deduplication, failure/recovery and actual-state registration repeats. |
| `src/techdocqa/ingestion/safety.py`, `online.py` | Optional capture of already handle-validated local bytes; reuse existing immutable snapshot publication with a storage namespace. Fetch/security code is unchanged. |
| `src/techdocqa/cli.py` | Add `process` using existing JSON/error/exit conventions; registration commands retain behavior. |
| `tests/test_normalization.py`, `test_loaders.py`, `test_versioning.py`, `test_online.py` | Synthetic normalization/format/hash/lifecycle/recovery/contention coverage and Phase 3A integration regressions. |
| `README.md`, `deployment/local_setup.md`, `docs/{IMPLEMENTATION_ROADMAP,LANGCHAIN_INGESTION_PLAN,DECISIONS,PHASE_3A_STATUS,REPOSITORY_STRUCTURE,TECHDOCQA_SDD,requirements_traceability}.md`, this checkpoint, `DEVELOPMENT_LOG.md` | Commands, scope, contracts, acceptance boundaries and verification evidence. |

No SQL schema/application-ID/version/table/index changes and no migration runner were needed after inspection. Existing CHECK/unique constraints and JSON columns represent the required lifecycle and duplicate mappings. Legacy-shaped Phase 2/3A metadata is reopened/finalized in tests; schema SQL is compared before/after. New optional JSON fields mean old readers cannot safely read newly processed records; downgrades remain unsupported. No dependency or lock changes: the existing TextLoader, BSHTMLLoader and PyPDFLoader stack is reused.

## Verification

All tests use small generated technical fixtures; no provider, Ollama service, external site or private PDF is required. The default network guard remains enabled. The processing worker additionally disables DNS/socket connection entry points. Tests cover model-constructor denial, offline reuse of online snapshots, title precedence, PDF pages/image-only errors, UTF-8/Latin-1, exact code/SQL/CLI tokens, Unicode/newlines/whitespace, empty/malformed content, deterministic hashes, metadata repeats, different-source duplicates, active supersession, stale candidates, rollback, snapshot corruption, real process death, interrupted committed outcomes, two-process lock contention and actual worker termination.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip freeze --all --exclude techdocqa
git diff --check
```

The one-command Git exception is required by the sandbox user's differing Windows ownership; no global Git configuration was changed.

| Check | Verified result |
|---|---|
| Baseline complete offline suite before edits | 160 passed, 2 skipped, 1 existing deprecation warning, 39.19 seconds. |
| Original regressions after implementation, before new tests | 160 passed, 2 skipped, 1 existing warning, 39.39 seconds. |
| Final complete offline suite after review | **214 passed, 2 skipped, 0 failed**, 1 existing deprecation warning, **124.52 seconds**. Includes all original 85 Phase 2 and 75 Phase 3A offline cases plus 54 new offline cases. |
| `pip check` | `No broken requirements found.` |
| Dependency consistency | All 67 nonproject installed packages exactly match the lock; all direct/dev constraints and installed project dependency metadata match `pyproject.toml`. |
| `git diff --check` | Exit 0; separate `--no-index --check` checks cover new files. |
| Source preservation | Requirements unchanged from baseline; SHA-256 `D458DDB2175D507004806738D3F87DE41405D40D39676B52995E07DB3D479949`. Its known line-62 whitespace is already in baseline and was not modified. |
| Security/dependency boundary | TOML catalog, fetcher, URL policy, HTML adapter, online worker, dependency declarations and lock have no diff. All original Phase 2 and Phase 3A offline tests remain in the complete suite. |
| Final file/document review | All 24 changed/new files reviewed before staging; 91 local documentation links resolve. All eight new files pass separate whitespace checks. No unrelated edits, new credentials/private input paths, private document content or downloaded documentation dumps are present. The historical user-home path in the original decisions text is unchanged baseline material. |

The two skips are the existing explicit live Kafka/Airflow tests. Live fetching was not rerun for this offline phase. The sole warning is the existing archived community-loader notice. No lint/type checker is configured; no such result is claimed. Dependency comparison used a temporary ignored local verification script, not an added dependency/test framework. No clean installation was repeated because dependencies and packaging configuration did not change.

## Acceptance boundaries and known limitations

The requested finalized-document layer is implemented. The [traceability update](requirements_traceability.md#implemented-acceptance-slices--phase-3b) maps synthetic coverage to AC-02.4, AC-03, AC-04 and the FR-05 document layer. Chunk/index-count portions of FR-05 and indexed FR-20 acceptance are untested and unimplemented because they belong to later phases; no fake zero-index capability is claimed.

Only Windows/Python 3.13.3 has been executed. Markdown structure metadata recognizes ATX headings and same-line backtick inline code; Setext headings and unusual Markdown constructs remain text for future parsing. Unmarked code in PDFs/prose cannot always be recognized, and PDF reading order/indentation depends on the loader. Repeated PDF edge removal is heuristic and does not reconstruct arbitrary/multi-line page furniture. Hyphenation requires existing vocabulary; ambiguous words are retained. Latin-1 can decode arbitrary high bytes, so control/replacement checks cannot prove linguistic correctness. Old records cannot distinguish an explicit user title equal to the filename from a filename fallback. Unicode database version is recorded, but cross-Python-version equivalence has not been executed.

Snapshot storage remains a trusted private single-user directory on a filesystem with hard-link support. Unreferenced complete artifacts after interruption/failure are retained, and no garbage collection is introduced. Before first local capture, missing/changed source bytes require re-registration. Normalization artifacts are bounded to eight times the configured source-size limit per artifact. Corpus licenses, documentation versions and usage permissions are never guessed.

The reference manifest remains unfrozen with zero selected files. No DDIA PDF/content, credentials, downloaded documentation dumps, corpus acquisition, chunking, embeddings, vector/BM25 indexing, search, reranking, QA, OCR, benchmark framework, UI or deployment is part of this work. The user additionally authorized committing and pushing the verified changes; publication outcome is reported in the handoff. Corpus/hardware/budget/reviewer/model and full quality/performance gates remain open. Next roadmap phase: Phase 4 segmentation/framework chunking.
