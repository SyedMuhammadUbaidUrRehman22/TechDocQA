# Development log

## 2026-10-21 — Phase 2 local registration implementation

Implemented from the Revision 3 requirements, current roadmap/SDD, Phase 1 checkpoint and Phase 2 plan. No prior development log existed; earlier foundation evidence remains in [PHASE_1_STATUS.md](docs/PHASE_1_STATUS.md).

- Fixed blank/whitespace allowed-directory and storage paths. Valid paths are stripped/canonicalized against the base TOML file; absent input roots are allowed during setup, while existing nondirectories or inaccessible configured paths fail safely.
- Replaced raw argparse diagnostics with section 8.4 JSON without argument/value interpolation. Preserved config-check/help/version behavior.
- Added checked SQLite schema version 1, repeatable initialization, foreign keys, unique source/byte registrations, per-file transactions, histories, run/attempt counters, explicit contention errors and process-death recovery under an OS lock.
- Implemented byte-only supported-format registration, actual-byte SHA-256, containment/open-handle checks, symlink/junction/race defenses, bounded reads and signature/archive/empty/size checks. PDF structural preflight enforces page bounds and terminates timed-out workers; isolated Python startup prevents document-directory module imports.
- Added JSON `ingest`, `status`, `list`, `history` operations and partial-batch failure reporting. Source URL/license/version metadata survives registration and is suitable for later framework `Document.metadata` propagation.
- Resolved registration identity/lifecycle/duplicate semantics in [DECISIONS.md](docs/DECISIONS.md). Byte candidates remain provisional with null normalized hash and inactive eligibility. Exact repeats reuse IDs; changed bytes link candidates; normalized content identity and supersession belong to Phase 3.
- Inspected the actual dependency set before adding pypdf 6.21.1; no LangChain loader, vector, NLP or model package was added. Planned framework loaders/splitters and metadata propagation in [LANGCHAIN_INGESTION_PLAN.md](docs/LANGCHAIN_INGESTION_PLAN.md).

Verification commands, final results, acceptance mapping and remaining gates are recorded in [PHASE_2_STATUS.md](docs/PHASE_2_STATUS.md). No model call, benchmark, corpus download or extraction is claimed. Existing user edits to the requirements document are preserved.

## 2026-10-21 — Interrupted work resumed and verified

Recovered the existing Phase 2 implementation without changing application code. Added the missing Phase 2 checkpoint and completed its acceptance/remaining-work mapping. The development environment passed all 85 tests; a newly created `.venv-phase2-resume-verify` installed the lock and editable package successfully and also passed all 85 tests, with no skips. Both environments passed `pip check`, matched all 49 locked packages exactly, and ran the installed configuration-check entry point successfully.

Checked 61 local documentation links, 24 original FR headings and 111 verbatim acceptance criteria. The requirements hash remains unchanged from the prior review; its pre-existing table-formatting/trailing-space edit remains preserved. No provider/model operation, corpus acquisition, Phase 3 implementation or remote publication was performed.

## 2026-10-21 — Phase 3A controlled online documentation ingestion

Inspected requirements, existing contracts/loader plan and all affected callers before implementing the selected optional URL slice. Added the single TOML catalog (Kafka/Airflow enabled; PostgreSQL/Spark/Redis/Docker disabled), public DNS/IP-pinned HTTPS fetches with bounded isolated processing, LangChain HTML extraction preserving code/structure, immutable raw/text snapshots and existing-registry URL candidates/retrieval provenance. Existing local identities, schema version and provisional eligibility are preserved. Added existing-command online CLI modes and an unfrozen runtime manifest projection; reference corpus requirements remain open.

Final clean-install offline suite: **160 passed, 2 skipped, 0 failed** (one upstream loader deprecation warning). Explicit final live smoke: **2 passed**, Kafka and Airflow, 75 offline cases deselected. Clean installation, 67-package exact lock, `pip check`, installed configuration CLI and wheel build passed. The original 85 Phase 2 tests remain covered. Plan/conflicts, exact commands, architecture, source activation, security/dependency limitations and remaining course gates are recorded in [PHASE_3A_STATUS.md](docs/PHASE_3A_STATUS.md).

Final document checks verified 78 local links, all 24 FR headings/111 AC lines and the unchanged requirements hash. All 49 Phase 2 dependency pins are retained. Full `git diff --check` reports only the preserved pre-existing requirements-table whitespace; the remaining changes and all new files pass whitespace checks.

## 2026-10-22 — Phase 3B normalized document finalization

Reconciled the requested Phase 3B with the authoritative roadmap: it is the remaining Phase 3 local parsing, normalization and versioning work; Phase 4 chunking remains deferred. Added offline `process` after unchanged registration/fetching, existing-package local LangChain loaders, code-preserving deterministic normalization, immutable extracted/normalized artifacts and atomic registry finalization. Same-source normalized duplicates resolve to existing finalized versions while retaining byte candidates/provenance; changed content supersedes atomically, and failed/interrupted work preserves the prior active version. Existing SQL schema and dependency lock are unchanged.

Final complete offline suite: **214 passed, 2 skipped, 0 failed**, one existing loader warning, **124.52 seconds**. Includes all original 160 offline cases plus 54 new cases. Exact commands, acceptance boundaries and dependency/whitespace/source-preservation evidence are recorded in [Phase 3B status](docs/PHASE_3B_STATUS.md). All 67 installed nonproject packages match the unchanged lock and `pip check` passes; all 91 local documentation links and all 24 changed/new files were checked. No models, live sites, privately held PDF, chunking, indexes, retrieval or corpus freeze were involved. After verification, the user additionally requested a commit and push of the completed changes.

## 2026-10-24 - Phase 4 sentence spans and framework chunking

Committed the reviewed corpus checkpoint as `1ad47d0` (`chore: freeze reviewed reference corpus and verification evidence`) before implementation. Added offline `chunk` using the existing LangChain splitter, bounded network-disabled worker, immutable snapshots and transactional registry JSON metadata; SQLite schema/version 1 and the frozen source manifest remain unchanged. Sentence spans and exact chunk source offsets preserve page/heading/code provenance, with separate occurrence IDs and text hashes. Repeats skip verified artifacts; explicit config changes activate atomically, and failures/recovery retain prior chunks.

At the user's request, installed signed Ollama 0.40.10 and both selected models. Verified `nomic-embed-text:latest` metadata: BERT/WordPiece, context 2048 despite `num_ctx=8192`, separate from the Qwen generation tokenizer. Without an exact provider token counter, the recorded conservative input bound caps requested 1000-character chunks to 507, overlap 150/minimum 100. No inference was run. The public reference yields **1,609 chunks**; private DDIA adds **3,934**, so the combined 21-document set has **5,543** and exceeds the reference chunk target. Repeating all selected versions skipped all 21 unchanged artifacts.

Complete reviewed suite: **243 passed, 2 skipped**, one existing warning, **129.46 seconds**. Final focused suite after the protected-indentation guard: **30 passed**, **92.64 seconds**. The final corpus reconstructs **13,898 spans across 43 normalized Documents/pages**, retains **465 fitting code blocks**, and passes SQLite integrity/foreign keys, source and chunk verification, configuration and `pip check`. Parallel review fixed paragraph/code-line boundaries, old-policy artifact verification and portable source-key counts; the selected corpus was regenerated under the final policies and all 21 repeats skipped. Exact evidence, model digests, counts, commands and acceptance limits are in [Phase 4 status](docs/PHASE_4_STATUS.md). Indexes, embeddings, retrieval, QA and P1 NLP remain later work. The user subsequently requested delivery: push the corpus chore checkpoint first, then commit and push the Phase 4 implementation separately.
