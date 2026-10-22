# TechDocQA implementation roadmap

Status: roadmap proposed 2026-10-09; implementation checkpoint 2026-10-22. Source: [requirements](../TechDocQA_Requirements_v2.md), contents Revision 3. Phase 1 foundation, Phase 2 registration/local safety, the selected Phase 3A online HTML slice and Phase 3B parsing/normalization/version finalization are implemented. Phase 1 corpus/hardware/budget/reviewer gates and Phase 4 onward remain open. Source release stages and priorities are preserved; an early slice does not complete a whole FR.

Current checkpoint: [Phase 3B](PHASE_3B_STATUS.md) completes the remaining Phase 3 implementation through an offline `process` step after registration/extraction. Phase 3A fetching/security and registration CLI behavior are retained. The optional URL slice does not complete the remaining Phase 12 features. Corpus/hardware/budget/reviewer decisions remain open; models, search and QA remain deferred. See [contracts](DECISIONS.md#phase-3b-normalization-and-finalization-2026-10-22) and [development log](../DEVELOPMENT_LOG.md).

All future test paths are proposed in [traceability](requirements_traceability.md). See [repository structure](REPOSITORY_STRUCTURE.md) for component paths and [decisions](DECISIONS.md) for D/Q gates. Default tests run offline with mocks. Real provider/model/human benchmarks are separate recorded gates and never substituted by mock results.

## Phase 0 — Planning (completed)

- Objective: inspect the full source and repository; produce a consistent design without application implementation.
- FRs: planning coverage of FR-01–FR-24, C-01–C-07, DS-01–DS-06, NFR-01–NFR-11; no FR marked implemented.
- Files: the five requested documents under docs; source unchanged.
- Dependencies: source available; inspect ancestor Git scope and tooling.
- Verification: compare 24 original FR headings/priority/dependency lines and all original AC lines against traceability; check SDD/roadmap mapping coverage and local Markdown links; inspect final changed files and source hash.
- Done: all FRs accounted for, assumptions labeled and approval gates explicit.
- Risks: source ambiguities and unverified dependency/model choices. Phase 1 requires plan approval.

## Phase 1 — Approved setup and corpus specification

- Objective: establish the minimal installable Python package and test tooling; agree on reference corpus, profiles and evaluation policy.
- FRs: FR-01/02/11/16/19/22/23 foundations only; C-01–C-07, DS-01–DS-06, NFR-05/07/08/09/10/11.
- Files: pyproject.toml, requirements.lock.txt, .gitignore, README, settings.py, schemas.py, config/default.toml and profiles, datasets/corpus_manifest.json, initial settings/schema tests.
- Dependencies: approval of D-01–D-07/D-13–D-15, Python baseline, dedicated Git scope, corpus technologies/licenses, model profiles, hardware and budget. Resolve Q-02–Q-05/Q-08/Q-11/Q-13 before affected schemas. Later model identity verification may remain an explicit phase-5/7 gate.
- Verification: resolve compatible constrained dependencies and exact lock; clean virtualenv installation/package import; validate settings/redaction and schema errors; check manifest 15–30 docs, <=50 MB, 3–5 technologies and required format counts. Collect public/license terms with permission for later source acquisition. No bulk model download implicit in setup.
- Done: reproducible package/test commands, placeholder-free nonsecret settings, approved dataset manifest/schema and recorded pending provider integration gates. Actual dependency versions become verified here.
- Risks: Python PATH currently 3.9.13; proposed 3.11+ needs installation/selection approval. Home-directory Git root must not be used for project-wide staging. Exact costs/hardware cannot be claimed before measurement.

## Phase 2 — Registry, registration and local safety

Detailed sequence, prerequisite decisions, acceptance boundaries and tests: [Phase 2 plan](PHASE_2_PLAN.md). This means roadmap Phase 2, not priority P2 optional scope.

Implementation checkpoint: registration, SQLite history/runs/attempts, local limits/containment, PDF page preflight, sanitized JSON errors and ingest/status/list/history are implemented. Current offline acceptance evidence is in [PHASE_2_STATUS.md](PHASE_2_STATUS.md). Raw-byte duplicate candidates remain separate from normalized finalization; no complete FR-02/05/20/22/23 claim. The Phase 1 corpus gate remains open independently.

- Objective: bounded per-file registration and traceable run/status records.
- FRs: FR-01 (local), FR-02 registration, FR-20 registration/history, FR-22 ingest/status slices, FR-23 local limits/paths/secrets slice.
- Files: registry.py, ingestion/safety.py, initial pipeline.py, cli.py, schemas.py; test_ingest.py, test_registry.py, test_status.py, test_safety.py, test_cli.py and DS-05 synthetic fixtures.
- Dependencies: Phase 1 package foundation; Q-02/04/05 state/source/attempt contracts resolved under the user's Phase 2 implementation instruction, with Q-06 registration boundary recorded. Max file/page/time defaults retained. Corpus selection remains open but does not block synthetic registration tests.
- Verification: AC-01.1–01.5; relevant AC-02.1/02.2; run counts/error redaction; invalid signatures/formats, missing/oversized paths, allowlist traversal and page bounds before full parsing. Enforce actual parser timeout when extraction lands next phase.
- Done: valid inputs register, batch failures isolate, required metadata/history persists, errors match section 8.4 and secrets remain absent. No claim of complete processing FRs yet.
- Risks: pre-registration failures need nullable document ID/run association; .pdf signature/page count is validation, not complete PDF safety. CLI is partial until phase 8.

## Phase 3A — Controlled online HTML ingestion

User-selected early URL slice of FR-01/FR-23, with online HTML extraction and FR-02/FR-20/FR-22 integration. The TOML catalog selects finite official Kafka/Airflow pages; four other approved sources start disabled. DNS/IP-pinned HTTPS fetching precedes local LangChain loading in a bounded worker. Existing SQLite JSON columns retain URL identity, raw/text snapshots and per-retrieval provenance; schema version 1 and local keys remain unchanged. No normalized versions, chunks or indexes are created. See [plan](PHASE_3A_PLAN.md), [implemented decisions](DECISIONS.md#phase-3a-online-contracts-2026-10-21) and [verification](PHASE_3A_STATUS.md).

## Phase 3 — Parsing, normalization and versioning

Phase 3B is the user's name for this remaining Phase 3 work; the original roadmap had no distinct 3B entry or indexing responsibility. Local LangChain loaders, code-safe deterministic normalization, immutable extracted/normalized artifacts and transactional finalization now implement this boundary. `ingest` retains byte registration; `process [version_ids ...]` completes it offline and can consume Phase 3A snapshots without a fetch. See [checkpoint and acceptance limits](PHASE_3B_STATUS.md). The original plan below remains the scope; no Phase 4 work is included.

- Objective: source-preserving text extraction and deterministic duplicate/change decisions.
- FRs: FR-03, FR-04, FR-05 P0; remaining title capture FR-02, processing history FR-20 and parsing limits FR-23.
- Files: ingestion/loaders.py, normalization.py, pipeline.py, registry.py and snapshots; test_loaders.py, test_normalization.py, test_versioning.py and fixture files.
- Dependencies: phase 2; Q-04/05/06/10/11 approval. Framework loader selection checked against pinned release.
- Verification: all original AC-03/04/05; PDF known sentences/pages and image-only error, HTML boilerplate markers, Markdown hierarchy/intact fences, Latin-1 fallback; technical token preservation/idempotent normalization/hyphenation; exact/normalized/renamed duplicates and changed content; title precedence; parser timeout termination.
- Done: extracted/normalized snapshots and hashes are reproducible, every ingestion attempt has a decision, immutable versions follow approved status/supersession policy; differently named duplicate adds no indexing work by default.
- Risks: code normalization conflict, same basename source collisions, failed new-version eligibility. Resolve these explicitly rather than inventing status enum values.

## Phase 4 — P0 segmentation and framework chunking

- Objective: retrieval chunks with complete source/section/page provenance and stable config identity.
- FRs: FR-06 minimal, FR-10; FR-02 chunk propagation and FR-20 chunk stage.
- Files: processing/segmentation.py, chunking.py, registry/schema extensions; test_segmentation.py, test_chunking.py.
- Dependencies: phase 3; approved Q-03/09/10/11; embedding profile input limit/tokenizer information available without assuming unlimited input.
- Verification: AC-06.1–06.3 and all AC-10; full span reconstruction, repeat counts, code block/oversize behavior, minimum/size/overlap checks, provenance, explicit config reprocessing and reported corpus chunk count. Record token fallback effective config.
- Done: no empty chunks, approved size/merge exceptions documented, occurrence IDs resolve to versions and original sections/pages, corpus stays within approximate DS-01 chunk target or requires a documented dataset adjustment.
- Risks: overlap and tiny-section merge can violate hard size/code boundaries; identical chunk_text must not overwrite another source's provenance.

## Phase 5 — Independent lexical and persisted vector search; lifecycle

- Objective: query both baseline retrievers, rerun/rebuild safely and remove ineligible documents immediately.
- FRs: FR-11 P0, FR-12, FR-13, FR-21 storage/search slices; FR-02 vector projection, FR-20 full processing/idempotency, FR-22 search/withdraw/delete slices.
- Files: indexing/embeddings.py, vector_store.py, retrieval/lexical.py, search.py, registry/pipeline/CLI updates; test_embeddings.py, test_vector_store.py, test_lexical.py, test_lifecycle.py.
- Dependencies: phase 4; Q-02/03/06/07/15/16 resolution. Provider access/models are explicitly provisioned only in this approved phase; Chroma compatibility validated. Use mocks first. P0 entity filters use verified registry memberships seeded in tests; automatic extraction remains P1.
- Verification: all original AC-11/12/13 offline where possible; real provider AC-11.5 stability labeled separately. Test no-call cache reruns, invalid vectors, model collection separation, persisted/rebuilt identical rankings, technical token queries, category/technology/document/entity filter contract (entity enrichment arrives P1), offline BM25, immediate supersession/withdrawal and deletion cleanup. AC-21.1 QA and 21.3 evaluation remain later gates.
- Done: baseline search usable through CLI, counts stable on rerun, active registry gating prevents stale sources, index reconstructs from stored data. Failed provider does not block BM25/status. Any actual provider test reports configuration and result truthfully.
- Risks: approximate index repeatability, scalar null mapping, shared chunk_key ownership/deletion and cross-store partial failure; no atomicity assumption.

## Phase 6 — Smoke benchmark and retrieval metrics

- Objective: create reviewed calibration data and trustworthy baseline measurement before refusal tuning.
- FRs: FR-19 P0; FR-21 benchmark-deletion flag slice, FR-22 eval smoke slice; DS-04/06 and NFR-05/06.
- Files: evaluation/dataset.py, metrics.py, runner.py; benchmark_smoke.jsonl, review_log.md, reports/evaluation; test_evaluation.py.
- Dependencies: phase 5, frozen manifest, second reviewer; approve Q-12/13 metric/anchor policy. No QA or full reranker dependence for this P0 slice.
- Verification: 30 questions exactly 20 answerable/10 unanswerable proposed to satisfy both source counts; stable relevant anchors and graded labels; review disagreements resolved; hand-computed Recall/MRR examples; all smoke AC-19.1/19.3–19.5; repeat baseline metrics; flag deleted-source labels without editing dataset.
- Done: BM25/vector Recall@1/3/5 and MRR report with dataset/corpus/config identities, <5 min on recorded machine excluding downloads, per-question results and explicit unanswerable handling. If runtime fails, report failure and resolve before release.
- Risks: anchor mapping/rechunking, corpus drift, human review availability; data quality/calibration leakage must be acknowledged.

## Phase 7 — Framework QA and citation verification

- Objective: bounded single-question generation with stored source citations and explicit provider errors.
- FRs: FR-16, FR-17, FR-23 prompt handling, FR-22 ask slice. Development QA is not released until FR-18 calibration phase 8.
- Files: answering/generation.py, citations.py, settings/schemas/cli updates; test_generation.py, test_citations.py, prompt safety fixtures.
- Dependencies: phases 5–6, approved chat profiles/context limits and Q-07/08/15; use framework chain. Both provider adapters are configuration-selectable; P1 live switching demonstration remains phase 10.
- Verification: all AC-16/17; fake provider failures, length/context budgeting/evidence equality, unknown/no citation modes and stored source equality; real configured provider test and 10-question human review recorded separately (>=80% support source target); injection regression AC-23.3 on configured model, secrets scan AC-23.4.
- Done: typed QA preserves exact supplied evidence and required sources/count fields, strict citations default, no unhandled provider failure, required human/integration evidence recorded. Runtime dependency failure never becomes a false insufficient-evidence claim.
- Risks: local model context and citation format compliance, semantic support vs label validity, provider timeouts and output variability.

## Phase 8 — Calibrated refusal and P0 release gate

- Objective: complete trustworthy baseline QA and CLI.
- FRs: FR-18, FR-19 calibration slice, FR-21 QA slice; complete P0 FR-16/17/22/23 and cumulative FR-01–06(minimal), FR-10–13/20.
- Files: answering/sufficiency.py, generation/context integration, calibration/config records, CLI smoke workflow, evaluation reports; test_sufficiency.py, lifecycle/CLI tests.
- Dependencies: phases 6–7; Q-07 approved transforms/thresholds for each enabled P0 mode. Calibration uses smoke benchmark and logs run ID.
- Verification: AC-18.1–18.5 (>=90% refusal among 10 out-of-domain; >=85% answered among 20 answerable), call counters for gate failures, empty/filter-empty distinction, post-context-trim sufficiency, generation_error separation; AC-21.1 and CLI help/errors/end-to-end ingest/search/ask/withdraw script. Reconcile each P0 AC to actual results.
- Done: all P0 criteria satisfied or a failed gate explicitly blocks P0 release; active thresholds/config IDs recorded in responses. Baseline can be demonstrated with offline unit tests and separate real-model evidence.
- Risks: score-scale mismatch and reused thresholds, benchmark overfitting; source targets are not waived by small sample size.

## Phase 9 — P1 NLP enrichment

- Objective: improve structured metadata without sacrificing technical text/provenance.
- FRs: FR-06 full, FR-07, FR-08, FR-09; filter extensions FR-12/13.
- Files: processing/enrichment.py, segmentation.py, registry metadata/search projections, optional NLP extras/config; test_entities.py, test_keyphrases.py, test_classification.py and annotated fixtures.
- Dependencies: P0 gate phase 8, approved P1 library choices and Q-11/14/16; labeled fixture sizes/targets and multi-category filter semantics resolved.
- Verification: AC-06.4 boundary F1>=0.95 on 50 annotated sentences; every AC-07/08/09 including verified entity filter, 20 labeled chunks, five keyphrase documents and >=two corpus documents/category; user category precedence, out-of-domain unclassified. Keep source numeric targets until explicit amendments.
- Done: enrichment is queryable, propagates to retrievers safely, configs/methods/costs recorded, actual labeled results meet gates. No claim of accuracy from rules alone.
- Risks: corpus category coverage, provisional thresholds, score direction, optional library/model overhead. No paid NLP enrichment by default.

## Phase 10 — P1 hybrid, reranking, full evaluation and provider demonstration

- Objective: measure enhancements and demonstrate configuration-only provider switching.
- FRs: FR-14, FR-15, FR-19 full, FR-22 provider demo; C-07. Recalibrate FR-18 for newly enabled modes.
- Files: retrieval/fusion.py, reranking.py, search/sufficiency settings; benchmark_full.jsonl, evaluation runner/reports, provider profiles; test_fusion.py, test_reranking.py and expanded evaluation tests.
- Dependencies: phases 8–9, approved D-11/12 and Q-07/08; exact reranker/model provision explicitly authorized at this stage; both providers available for live demo.
- Verification: all AC-14/15/19 full; hand RRF, duplicate ranks, degraded path, disabled/max/failing reranker; four-configuration numerical table including per-technology results; full <=50 questions retains smoke with >=15% unanswerable; >=20 manually evaluated answers or recorded/costed judge; same ask command under both configured providers, rebuild if embedding model changes. Record costs/latency and refreshed refusal calibration for hybrid/reranker/degraded modes.
- Done: full evaluation evidence and provider-switch result recorded; default reranking remains disabled unless measured benefit supports an approved change. All P1 criteria/targets checked, not presumed.
- Risks: small sample variance, model downloads/hardware, new score scales and expensive judge alternatives.

## Phase 11 — Required operational verification and delivery

- Objective: verify required safety, reproducibility, performance, cost/privacy and clean-machine setup; keep optional FR-24 separate.
- FRs: cumulative P0/P1 regression, especially FR-11/12/19/20/21/22/23; C-06/07, NFR-01–NFR-11.
- Files: README, deployment/local_setup.md, exact dependency lock/config snapshots, reports and traceability status updates; targeted failure/restart tests if remaining risks require them.
- Dependencies: phase 10, recorded reference CPU/RAM/GPU/models/provider budgets and agreed profiling procedure.
- Verification: required ACs and tests mapped to evidence; clean virtualenv setup; full ingest timing, retrieval/QA p95 with stage timings, 2x headroom separate from frozen corpus; exact repeated retrieval/rebuild; secret scans; corpus licensing, provider privacy disclosure and dated API cost estimate or local hardware statement for ingest+full benchmark.
- Done: measured required targets and quality gates pass, or failures are documented and fixed before claiming release. User-facing documentation enables reproduction. This phase does not expand P2 scope.
- Risks: hardware/latency or cost target failures may require approved model/corpus choices and rerunning affected evaluation, not silently weakening NFRs.

## Phase 12 — Separately approved P2 work

- Objective: choose only wanted optional reliability/polish features.
- FRs: FR-24; URL slices FR-01/23; web UI FR-22; cross-version reuse FR-05/11.
- Files: existing CLI/logging/pipeline/settings modules plus minimal optional URL/UI module only if selected; test_observability.py and feature-specific tests/documentation.
- Dependencies: phase 11 and explicit feature scope approval, Q-03/15 cache ownership/cleanup; URL SSRF and UI privacy decisions before implementation.
- Verification: selected original ACs including all AC-24 when selected, URL loopback/metadata/redirect/destination controls, unchanged CLI/schema behavior, retry idempotency and no paid secrets/text in logs; cross-version reuse does not lose document/section/version provenance.
- Done: selected optional FR slices pass tests and are recorded; unselected optional work stays clearly deferred. No API endpoints or new distributed infrastructure implied.
- Risks: SSRF, dependency bloat, local-model/UI exposure and shared-cache deletion correctness.

## Recommended next action

Next is Phase 4 segmentation/framework chunking, consuming verified finalized Documents from Phase 3B. Preserve code/heading/page provenance and apply active-version/duplicate eligibility. Complete corpus selection and hardware/budget/reviewer gates; models remain deferred to Phases 5/7.
