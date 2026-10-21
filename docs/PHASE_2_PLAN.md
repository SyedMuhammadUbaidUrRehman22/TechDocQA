# Phase 2 implementation plan

Status: original plan/review retained below; implementation executed 2026-10-21 under the user's Phase 2 instruction. See [actual behavior and verification](PHASE_2_STATUS.md) and [resolved registry contracts](DECISIONS.md#implemented-phase-2-contracts-2026-10-21). This is **roadmap Phase 2**, registry, registration and local safety, separate from priority P2 optional features. Findings and proposed work below describe the earlier review; the checkpoint identifies what is now implemented versus later work.

Sources: [Phase 1 checkpoint](PHASE_1_STATUS.md), [roadmap](IMPLEMENTATION_ROADMAP.md), [decisions](DECISIONS.md), and [Revision 3 requirements](../TechDocQA_Requirements_v2.md).

## Review outcome and unfinished Phase 1 work

The installable foundation is verified, but Phase 1 as a whole is incomplete. The draft manifest has zero documents and no selected technologies. There is no registry, ingestion pipeline, parser, index or answering implementation.

| Item | Current evidence | Required next step / timing |
|---|---|---|
| Foundation package and dependency lock | Existing 13 tests pass; both existing environments match the lock and pass `pip check` | Retain these checks during Phase 2. No fresh installation was performed in this review. |
| Corpus and manifest, DS-01–DS-04 | `datasets/corpus_manifest.json` is draft with empty lists | Select 15–30 permitted files across 3–5 technologies, <=50 MB, including >=3 Markdown, >=3 HTML, >=3 text PDF and >=1 TXT. Record sources, license/terms and byte hashes. Compute normalized content hashes in Phase 3; report the approximate <=3,000 chunk target in Phase 4. |
| Synthetic fixtures, DS-05 | No fixture directory or ingestion tests exist | Create duplicate, modified, differently named, image-only PDF, unsupported-format and Latin-1 TXT fixtures during Phases 2–3. Keep them separate from the corpus. |
| Hardware and budget | Not recorded | Record reference CPU/RAM/GPU and budget policy before provider provisioning and performance/cost claims. |
| Evaluation reviewer | Not selected | Identify a second reviewer before the Phase 6 benchmark review. |
| Chat and embedding models | Intentionally unset under prior user direction | Preserve deferral to Phases 5/7; then record licenses, model identity/revision, embedding dimension and input/context limits. They are not needed for offline registration tests. |
| Provider portability | Source still requires configuration-driven OpenAI/Ollama support | Preserve this later obligation unless the source is explicitly amended. No provider call is needed in Phase 2. |
| Registry identity and state | Q-02/Q-04/Q-05 and the SQLite choice remain proposals | Settle the contracts below before persistence code. |

Corpus selection remains a Phase 1 completion gate. Synthetic registration work can be developed independently once its identity/state contracts are settled; that does not complete the corpus gate.

## Confirmed foundation gaps to address first

1. **Allowlist entries can be empty.** `Settings.allowed_directories` validates the list length but not each string. A TOML entry of `""` is accepted and resolves to the configuration directory. Reject empty and whitespace-only entries before path resolution, and reject blank storage paths. Validate effective paths again at the ingestion boundary. Current tests cover only the valid default path.
2. **CLI argument errors bypass the standard error response.** `argparse.parse_args()` runs before the error handler. An unknown flag returns exit code 2, emits plain usage text and echoes its argument value. Extend the CLI so invalid commands/arguments return section 8.4 errors without echoing raw values; keep help/version successful. Add regressions for invalid command, unknown option and invalid typed argument, including a generated sensitive marker.
3. **Planning documents contain stale status text.** The roadmap still told the reader to begin Phase 1. Its current status and next action are updated by this review. Historical planning assumptions in the SDD/decisions/structure documents remain historical, subject to their current-checkpoint notices.
4. **The requirements file already has an uncommitted formatting change.** A split table row changes its hash but none of the 24 FRs or 111 AC lines. Preserve that existing edit; the original hash in Phase 1 is historical evidence, not the current working-file hash.

These are review findings, not fixes completed by this planning task. Path enforcement and the complete CLI contract were already scheduled for implementation after the foundation.

## Phase 2 scope and acceptance boundaries

| Requirement slice | Phase 2 evidence | Remaining work |
|---|---|---|
| FR-01 local registration | AC-01.1–01.5: supported local files register; unsupported/mismatched/missing/oversized inputs fail independently | End-to-end extraction/indexing remains later. URL input is optional priority P2. |
| FR-02 registration metadata | AC-02.1/02.2 for registered records, required IDs/UTC time/hash/status, optional null/default fields, explicit title then filename | Format-derived title AC-02.4 in Phase 3; chunk and vector propagation AC-02.3/02.5 in Phases 4–5. |
| FR-20 registration/run history | AC-20.1–20.3 for registration counts, persisted history and redaction, including failures before document IDs exist | Processing stages and indexed rerun idempotency AC-20.4 remain later. |
| FR-22 ingest/status CLI | Implement and test `ingest`, `status`, JSON output and standard argument errors | Search, ask, withdraw, delete and evaluation arrive in their phases. AC-22.1/22.3/22.4 cannot be claimed complete here. |
| FR-23 local limits/paths/secrets | File-size and PDF-page preflight, allowed-directory enforcement, bounded PDF inspection and redaction tests | Full extraction timeout in Phase 3; configured-model injection regression in Phase 7. No complete FR-23 claim. |

## Contracts to settle before registry coding

These are proposed implementation decisions, not approvals inferred from this review. Use small examples and a transition table in `DECISIONS.md` to settle each one before its dependent implementation.

| Decision | Proposed contract | Required examples / constraint |
|---|---|---|
| D-06 storage | Python standard-library SQLite, foreign keys enabled, parameterized queries, explicit schema version and short transactions | Reopening preserves records; injected failure rolls back the per-file operation. No ORM or database service. |
| Q-02 lifecycle | Separate processing status from lifecycle/eligibility. Registration is not retrieval eligibility. Keep the source status vocabulary; do not invent `active` as a processing stage | Transition table for registration success/failure and a future indexed/superseded/withdrawn version. Expose the distinction in status output. |
| Q-04 source identity | Preserve filename plus optional logical name; specify Windows case/Unicode handling and an explicit collision response for equal basenames at different paths | Same path twice, same basename in two allowed directories, explicit logical name and path aliases. Canonical resolved paths enforce safety; they do not silently replace the source key definition. |
| Q-05 attempts versus versions | Allocate an attempt per input, including rejected inputs. Distinguish provisional registration from a finalized normalized version; normalized duplicates resolve to the existing version in Phase 3 | Write the observable registration/finalization outputs for first import, exact repeat, normalized-only duplicate and changed content. Failed attempts must not become phantom committed versions. Do not enforce uniqueness on nullable `content_hash` as a substitute for this policy. |
| Q-06 affected boundary | Record the intended supersession point before adding constraints on active versions | Specify what remains eligible when a changed source fails. Implement the full indexing/eligibility policy in later phases. |

Q-03 chunk ownership, score policies, chunk normalization and evaluation semantics remain gates for their affected later phases. Phase 2 does not need chunk, vector, QA or benchmark tables.

## Implementation sequence

### 1. Close foundation validation gaps and define registration contracts

- Reject blank allowed-directory/storage entries. Keep valid relative paths anchored to the base TOML file.
- Handle argument validation through the existing error schema, including sanitized messages and nonzero exit codes. Preserve `config-check`, help and version behavior.
- Define typed section 8.1 registration results, registration metadata, run summaries and timestamped events. Failed pre-registration inputs retain nullable document/version IDs and a run/attempt association.
- Record the settled D-06/Q-02/Q-04/Q-05 decisions and Q-06 boundary. Add focused tests for these contracts before building their callers.

Deliverable: existing foundation tests plus meaningful validation/schema regressions pass offline.

### 2. Add the SQLite registry

- Add `src/techdocqa/registry.py` with only the records needed now: documents, provisional/final version representation chosen above, runs, attempts and status/decision events. Store failures on attempts or events without an unnecessary second logging system.
- Persist source identity, required registration metadata, optional null/default metadata, UTC timestamps, raw hashes and attempt outcomes. Keep `content_hash` unset until normalization.
- Add lookup by document ID, run ID and status. Invalid inputs remain visible through their run even when no document was created.
- Make each file's registration/history updates transactional; a failed file rolls back its own writes without losing its attempt error or earlier successful files. Never overwrite an existing registry on schema mismatch.

Deliverable: restart persistence, source collisions, foreign-key integrity and rollback tests pass.

### 3. Add local input preflight

- Add `ingestion/safety.py`. Resolve paths and enforce containment with path-aware comparisons, including symlinks/junctions where supported. Test traversal, sibling-directory prefixes and alternate-drive paths on Windows. An empty allowlist must never mean unrestricted access.
- Check accessibility and regular-file type; enforce the actual byte limit before parsing/hashing beyond that limit. Validate supported extensions and signatures, reject archives and a false `%PDF` claim with readable standard errors.
- Inspect PDF page count without full text extraction and enforce the 500-page default. Bound inspection by the configured 60-second timeout and terminate timed-out work. A signature/page count is not full PDF validation.
- Select and verify the smallest PDF inspection dependency only when needed, consistent with the proposed pypdf/framework-loader direction. Update the tested lock when a dependency is actually added; do not add NLP/vector/model packages here.
- Hash the validated bytes and ensure the registered snapshot/hash cannot silently refer to a different file after replacement. Map permission errors and unsafe races to per-file failures.

Deliverable: file/path/signature/size/page/timeout tests pass without a provider or text extractor. Image-only PDFs may register now; their `NO_TEXT_EXTRACTED` outcome belongs to Phase 3.

### 4. Wire batch registration and CLI status

- Add `ingestion/pipeline.py` to create a run, expand directory inputs deterministically, register each file independently and finalize counts/status/timestamps.
- Count `processed` as successfully registered in this phase, explicitly identifying the registration stage. Do not present it as fully indexed. Leave normalized deduplication and its skipped counts to Phase 3 unless the settled Q-05 policy defines a safe exact-repeat shortcut.
- Add `ingest` and `status` to `cli.py`. Support optional source metadata and settled logical-name handling, document/run/status queries, and `--json` output based on section 8. Use `config-check`'s configuration-loading behavior consistently.
- Return a nonzero exit for a failed or partially failed batch while retaining all per-file successes/errors in the response. Derive run status from actual outcomes: all success -> `completed`, mixed -> `completed_with_errors`, all failed -> `failed`.
- Sanitize failures before persistence and before display, including argument/configuration errors and metadata-derived messages. Generate sensitive test values at runtime; never commit a literal test credential.

Deliverable: a new process can register a fixture directory, then retrieve its document, run and status history through the CLI. A 5-valid/2-invalid batch reports 5 registered and 2 failed.

### 5. Verify and update completion evidence

| Test area | Required cases |
|---|---|
| `test_ingest.py` | Valid Markdown/TXT/HTML/text PDF, unsupported `.docx`, renamed text `.pdf`, missing/unreadable/oversized input, 2-valid/1-invalid directory and 5-valid/2-invalid run |
| `test_registry.py` | Required metadata/defaults, chosen identity/collision policy, independent attempts, restart persistence, foreign keys and transaction rollback |
| `test_status.py` | Document/run/status queries, timestamped history, terminal run counts and failures with null document IDs |
| `test_safety.py` | Blank allowlist entries, containment/traversal, symlink/junction escape where available, size/page limits before extraction, bounded PDF inspection, archive rejection and sensitive-marker masking |
| `test_cli.py` | Existing config check; ingest/status JSON round trips; malformed arguments return standard errors; mixed-batch exit; no sensitive marker or ordinary stack trace |

Create only fixture files that these tests need. A registration fixture is not evidence of parser correctness. Keep DS-05 parser/versioning cases explicitly assigned to Phase 3 until exercised there.

Run the expanded offline suite, `pip check`, CLI smoke workflow, and a clean lock installation if dependencies change. Update [traceability](requirements_traceability.md) by verified AC/slice rather than marking whole FRs complete. Record commands/results and remaining gates in a Phase 2 checkpoint; update README and roadmap to match.

Phase 2 is complete when local registration and restart-visible status work, invalid files remain isolated and traceable, local safety limits are enforced, and the checks above pass. Model selection, extraction, normalized duplicate decisions, indexing, retrieval, QA, benchmarks and optional priority P2 features remain assigned to their later phases.

## Verification performed for this review

- Existing `.venv` suite: **13 passed** on Windows/Python 3.13.3.
- `pip check` and `config-check`: passed in both existing `.venv` and `.venv-verify`. Both frozen dependency inventories exactly match `requirements.lock.txt`.
- Focused offline probes reproduced acceptance of an empty allowlist entry and the CLI argument-error format/value-echo gap. These probes do not add regression tests or fix application behavior.
- All **24 FRs and 111 original AC lines** remain present; all 111 AC lines match traceability.
- The existing requirements edit only splits a table row. Current working-file SHA-256: `D458DDB2175D507004806738D3F87DE41405D40D39676B52995E07DB3D479949`.
- No fresh environment installation, remote publication check, provider call, model download, parser integration or benchmark was performed. The second environment's test suite was not rerun in this review.
