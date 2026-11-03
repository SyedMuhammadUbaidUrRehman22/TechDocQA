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

## 2026-11-02 - Review corrections to Phases 2-4

The user requested a review of the project and SDD, then asked for every finding to be fixed and pushed. Before the fixes, an uncommitted working copy of this log and the SDD had rolled both back to older content; that diff was saved outside the repository and the files were restored. Fixed: stranded content from stale `duplicate_of` links; removal of table values mistaken for page numbers; mid-word overlap and missing sentence boundaries; the 507-character cap; repeated-header removal and idempotence; false headings in TXT/PDF; multi-line HTML headings; over- and under-broad cookie/banner removal; BOM and damaged UTF-8 decoding; non-ASCII CLI crashes; undecodable filenames aborting a batch; missing status history; metadata over-masking; SVG titles; sentence splits after `?`/`!`; the empty-run exit code; assert-based corpus verification; and stale documentation. OpenAI chunking profiles now pass the chunking gate.

Corpus effect: one PDF's normalized text regained a value (`46`), so the manifest is dataset version 2, with a one-off registry update that kept that version's ID and raw hash. All 21 selected documents were explicitly re-chunked: **816 public-reference and 1,919 DDIA chunks, 2,735 in total** (previously 1,609, 3,934 and 5,543). Mid-word chunk starts fell from 2,754 to 0. No inference ran and no corpus bytes were committed. Suite: **269 passed, 2 skipped**, one existing warning, **185.78 seconds**. Evidence is in [Phase 4 status](docs/PHASE_4_STATUS.md) and the [corrected contracts](docs/DECISIONS.md#review-corrections-2026-11-02).

## 2026-11-02 - Phase 5 search and lifecycle

Added local embeddings with stored vectors, Chroma through LangChain after a Windows gate in a scratch environment, BM25 that keeps technical tokens whole, common filters, `index`, `search`, `withdraw` and `delete`, and registry schema version 2. The real registry was copied to `data/registry.sqlite3.pre-phase5.bak` before its in-place upgrade.

All 21 selected documents were indexed locally: **2,735 entries, 2,727 stored vectors, 548 seconds, 0 failures**. A repeat run and a full rebuild each made 0 model calls with the provider unreachable, and restart and rebuild reproduced identical top-5 results. Complete offline suite: **328 passed, 2 skipped**, 510 seconds.

Real-corpus checks changed the work twice. The first identifier list included terms absent from the corpus, so it was replaced with terms that occur. BM25 rebuilt its index per query at about 1.75 s, so it now caches per process, reaching p95 0.138 s. Two results remain open: AC-12.1 on the real corpus at 124 of 152, where exact search scores the same so the index is not the cause, and warm vector search at p95 1.377 s against the 1 s target. Withdrawal and deletion were tested offline and not run on the real registry. Exact evidence is in [Phase 5 status](docs/PHASE_5_STATUS.md).

## 2026-11-03 - Phase 6 smoke benchmark and retrieval metrics

Added the FR-19 smoke runner: a JSONL loader with stable source-key and anchor labels, item-based Recall@1/3/5 and MRR, and `techdocqa eval`. The command writes JSON and Markdown reports with dataset, corpus, configuration, model, library and code identity. `search()` gained an optional source-key scope so evaluation searches only the frozen public reference; the private DDIA supplement is never searched or labeled. The CLI's search is unchanged. Deleted, withdrawn, out-of-scope and unresolved labels flag their questions without editing the benchmark (AC-21.3).

Claude Code drafted the 30 smoke questions at the user's request: 20 answerable, five per technology, and 10 out-of-domain. Every anchor resolved on the real corpus. **No second-person review has taken place**, so all questions are marked `draft` and every report says the metrics are provisional. On the public reference: BM25 Recall@5 0.925, MRR 0.708; vector Recall@5 0.925, MRR 0.783. Two full runs took 40.1 s and 35.1 s and had identical results fingerprints. Complete offline suite: **349 passed, 2 skipped**, 576 s.

One finding concerns Phase 5 code: each vector query lists Ollama's models to check the pinned digest, and that call took 2.6 to 3.0 s in one session, against 0.17 s for the embedding. It was left unchanged and is recorded in [Phase 6 status](docs/PHASE_6_STATUS.md), together with exact evidence and open items.

Follow-up the same day: the project owner reviewed the 30 questions and accepted all of them without changes. They are now marked `reviewed` (dataset sha256 `11710120...ccfb92faa`) and the review is logged in [review_log.md](datasets/review_log.md). The rerun `eval_28a37a3f76d44568a7cf869ad21f02d0` gave identical metrics. Q-12/Q-13 approval remains open.
