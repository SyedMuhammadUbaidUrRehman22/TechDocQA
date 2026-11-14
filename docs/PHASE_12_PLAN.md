# Phase 12 plan: retries, health check and logs (FR-24)

Status: **proposed and approved 2026-11-14.** The owner approved P12-1 to P12-6 with *"approved and push as you go"*, which amends P12-6: work is pushed as it proceeds. The decisions are recorded as [Phase 12 contracts](DECISIONS.md#phase-12-contracts-2026-11-14). The plan covers the part of [roadmap Phase 12](IMPLEMENTATION_ROADMAP.md#phase-12--separately-approved-p2-work) that the owner kept. On 2026-11-14 the owner was shown the four optional P2 items and said *"skip web ui and reuse"*. That keeps:
- FR-24, all four acceptance criteria (AC-24.1 to AC-24.4);
- the URL slice of FR-01 and FR-23, which needs evidence only (P12-5).

The web UI and cross-version reuse are out of scope. Sources: [Revision 3 requirements](../TechDocQA_Requirements_v2.md) FR-24 and the change note at line 797, the [SDD](TECHDOCQA_SDD.md) section 14, and the [Phase 11 report](PHASE_11_STATUS.md).

## Entry gate

- Phase 11 is closed and merged into `main` (`b041c0b`, pushed).
- This plan is on `feat/phase-12`.
- No baseline test run has been made for Phase 12 yet. Step 1 makes one.

## Local-only scope

| Requirement | Its hosted-API part | Phase 12 treatment |
|---|---|---|
| AC-24.3 | "or the API key removed" | Not applicable, local-only by owner decision. The Ollama-stopped case is tested |
| FR-24 behaviour 4 | A per-run token and cost summary when a paid API is used | Not applicable. No paid API is used |
| FR-24 behaviour 2 | The LLM provider in `check` | Ollama only |

## Invariants

1. **No retrieval or answering result moves.** Phase 12 does not touch search, ranking, prompts or thresholds, so the P0 fingerprint and every configuration ID stay as they are.
2. **Existing commands and schemas keep their behaviour.** The only additions are two new commands (`check` and `retry`), their result schemas, and new keys in the log lines. `ErrorDetail` does not change (P12-2).
3. **Logs hold no secrets and no document text.** The AC-20.3 and AC-23.4 tests, and the Phase 11 scans, must still pass.
4. **No new dependency.**
5. **Every new test uses mock models, and no Phase 12 step loads a model.**
   - Tests run in groups through `scripts/run_tests.py`, never as one `pytest` process.
   - Ollama tests are skipped unless `--live-model` is given, and offline tests are denied network access (`tests/conftest.py`).
   - One existing test in the `retrieval` group loads the real reranker when its files are downloaded, as they are on this machine: `test_the_pinned_cross_encoder_reproduces_its_model_card_and_repeats_exactly` (`tests/test_rerank.py:333`). Phase 12 does not touch the reranker, so its runs leave that test out: `python scripts/run_tests.py core retrieval -- -k "not pinned_cross_encoder"`.
   - The one optional real run (step 6) only lists Ollama's installed models.

## What already exists

| Piece | Already there | Gap |
|---|---|---|
| Failure classes | Every error carries `retryable` (`src/techdocqa/errors.py:10`), stored in `attempts.error_json` with the run and version (`src/techdocqa/registry.py:66`) | The word `permanent` appears nowhere |
| Recovery | Rerunning `index` re-embeds only the failed chunks (`tests/test_indexing.py:267`). Vectors are keyed by `chunk_key`, so a rerun adds no duplicates | No `retry` command; nothing finds what failed and reruns it |
| Empty PDF | An image-only PDF fails `process` with `NO_TEXT_EXTRACTED`, not retryable, status `extraction_failed` (`tests/test_loaders.py:48`) | Not reported as `permanent` |
| Health | `config-check` validates settings and reports `provider_connection_checked: false` (`src/techdocqa/cli.py:225`). `build_embeddings` already lists Ollama's models to check the pinned digest (`src/techdocqa/indexing/embeddings.py:64`) | No `check` command |
| BM25 when Ollama fails | BM25 search works while the embedding provider fails (`tests/test_indexing.py:275`); hybrid falls back to the surviving mode (`src/techdocqa/retrieval/search.py:316`) | Not reported anywhere as a dependency status |
| Logs | `data/logs/qa.jsonl`, one JSON line per question, with `timestamp` and `request_id` (`src/techdocqa/answering/generation.py:246`) | Lacks `level`, `component`, `run_id`, `document_id`. Nothing else logs: the workers turn logging off |
| URL slice | AC-23.5 tested in `tests/test_online.py` since [Phase 3A](PHASE_3A_STATUS.md) | None |

## Decisions to approve before building

| ID | Decision | Recommendation | Why, and the alternative |
|---|---|---|---|
| P12-1 | How a retry happens (AC-24.1) | **A manual `retry` command,** `retry [--run-id RUN]`. Each failed attempt is classified by its stored `retryable` flag first, then by its stage:<br>- **Not retryable**, at any stage: not rerun, reported as `permanent` with its code and stage. This covers bad formats at registration as well as an empty PDF at `process`.<br>- **Retryable, at `process`, `chunk`, `index` or `enrich`:** that stage's existing function reruns the version, as one new run. Today the stage errors marked retryable are `PARSE_TIMEOUT` and `SNAPSHOT_NOT_ACCESSIBLE` (processing), the embedding and vector-store errors (indexing), and `REGISTRY_BUSY` (any stage).<br>- **Retryable, at registration or online fetch** (such as `DNS_FAILED`): reported with the advice to rerun `ingest`, because `retry` has no record of the original paths or URLs.<br>- **No version recorded:** a stage stores the version on an attempt only after its start check passes (`src/techdocqa/registry.py:520`). An attempt that failed that check is reported with its code and no version.<br>**Recovered and default run:**<br>- A failure counts as recovered once a later run of the same stage has processed or skipped that version.<br>- Without `--run-id`, `retry` takes the most recent run that still has a failure not yet recovered.<br>- A permanent failure is reported on every `retry` until the document is fixed, withdrawn or deleted.<br>**Exit code:** 1 while anything remains failed, permanent failures included. | The lightest option. It is what the requirement names ("or a manual `retry` command") and what SDD section 14 assigns to FR-24. It reuses stage functions that are already idempotent. The requirement's other route, the provider client's retry settings (change note at line 797), doesn't exist here: the Ollama client is built with a timeout only (`src/techdocqa/indexing/embeddings.py:62`). A transient failure is not fixed until someone runs `retry`.<br>**Alternative:** an automatic bounded retry inside the indexing embedder. It changes `embedding_requests` counts, needs an injectable backoff so tests don't sleep, and needs the existing provider-failure tests rewritten to fail permanently. |
| P12-2 | Where `permanent` appears (AC-24.2) | **Only in the new outputs:** the `retry` result and the log lines (P12-4). `ErrorDetail` keeps `retryable` and gains no field. | It keeps invariant 2: no existing JSON output changes.<br>**Alternative:** a `failure: "retryable" \| "permanent"` field on every error, which changes every error output and the tests that compare them. |
| P12-3 | The `check` command (AC-24.3) | **Dependencies, in the requirement's order:**<br>- `registry`: opens and answers one read query.<br>- `vector_store`: opens the active profile's collection and counts its entries; empty counts as down.<br>- `bm25_index`: builds from the active chunks and answers one fixed query.<br>- `embedding_provider` and `llm_provider`: list Ollama's models with a 5 s timeout and compare the pinned digests. No model is loaded.<br>- `reranker`, only when reranking is enabled: its files match the pinned identity, without loading it.<br>**Statuses:** each dependency reports `ok` or `down` with an error code and its time. Overall is `ok` when all pass, `down` when the registry or BM25 fails (no search can run), otherwise `degraded`.<br>**Rules:** changes nothing in `data/` except adding its own log line (P12-4); prints JSON every time; exit 0 for `ok`, 1 for `degraded` or `down`. `config-check` stays as it is and still contacts nothing. | Matches FR-24 behaviour 2. Listing models costs the laptop nothing, where an embedding or chat call would load a model. The fixed 5 s timeout keeps `check` quick even though the model timeout is longer.<br>**Alternative:** exit 0 for `degraded`, so scripts treat a working BM25 fallback as success. |
| P12-4 | Logs (AC-24.4) | **Fields, from FR-24 behaviour 3:** `timestamp`, `level`, `component`, `run_id`, `document_id` and `request_id` on every line (null where they don't apply), plus `event` and safe values only: error codes, stages, counts, `retryable` or `permanent`.<br>**Streams:** "every log line" means every file TechDocQA writes under `data/logs`:<br>- a new `techdocqa.jsonl`, with each batch run's start and finish, each failed attempt, each `retry` decision and each `check` result;<br>- the existing `qa.jsonl`, which gains the four missing fields as new keys.<br>**Rules:**<br>- Third-party library loggers are not routed into these files, and the workers keep logging off.<br>- A setting turns the new log off, as `answering.query_log` does for `qa.jsonl`.<br>- No rotation, the same as `qa.jsonl`. | The fields are the requirement's own list. Third-party messages can't be guaranteed free of URLs, secrets or text, so they stay out. The registry's `events` table remains the record of decisions; the log does not replace it.<br>**Alternative:** route every Python logger to JSON, which would need a scrubbing filter for text nobody controls. |
| P12-5 | The URL slice (FR-01, FR-23) | **Record the evidence only.** AC-23.5 has been met since Phase 3A by `tests/test_online.py`, which runs offline in the `core` group. URL input in FR-01 has no acceptance criteria of its own. No new sources. | The work was done early as Phase 3A at the owner's request. |
| P12-6 | Delivery | **Local only.** Commits go on `feat/phase-12` and merge into `main` locally. Nothing is pushed until the owner says so. | Pushing is outward-facing. |

## Work sequence

Each step ends with its tests passing in the affected groups. `tests/test_observability.py`, the module the roadmap names, goes into the `retrieval` group in `scripts/run_tests.py`. Otherwise the runner refuses to start.

| Step | Work | Output and check |
|---|---|---|
| 0 | Approve or amend P12-1 to P12-6 | Recorded in [decisions](DECISIONS.md) as Phase 12 contracts. The roadmap's and decisions' "not selected" lines are updated then, not before |
| 1 | Baseline: the `core` and `retrieval` groups before any change, with the reranker test left out (invariant 5) | Pass counts recorded |
| 2 | The JSON log module and the new `qa.jsonl` keys (P12-4), first so later steps log through it | Tests for the log module and `qa.jsonl` |
| 3 | `retry` (P12-1, P12-2) | **AC-24.1:** a mock embedder fails one batch, `retry` reruns it, and the chunk, embedding and index counts equal a failure-free run, with no duplicate entries.<br>**AC-24.2:** an image-only PDF with no text, the fixture in `tests/test_loaders.py:48`, fails `process` with `NO_TEXT_EXTRACTED`. `retry` does not rerun it and reports it as `permanent`.<br>Also tested: a failure counts as recovered after a retry, the default run, and the report for an attempt with no version |
| 4 | `check` (P12-3) | **AC-24.3:** with the mock Ollama client unreachable, `check` reports `degraded` and names `embedding_provider` and `llm_provider`, and `search --mode bm25` still returns results.<br>Also tested: the `down` and `ok` cases, the reranker shown only when enabled, nothing in `data/` changed apart from the log line, and `--help` listing both new commands (AC-22.1) |
| 5 | AC-24.4 over every log line written in steps 3 and 4 | Each line parses as JSON and has the six fields. No fixture text and no test secret appears in any line |
| 6 | **Optional, the owner's choice:** one real `check` with Ollama running and one with it stopped | Lists models only, a few seconds each, no model loaded |
| 7 | Documents: README commands, `deployment/local_setup.md`, the traceability rows for FR-24 and the URL slice, the Phase 12 report, the roadmap and the development log. Every group once more, one at a time, with the reranker test left out | `docs/PHASE_12_STATUS.md` |
| 8 | Delivery under P12-6 | Recorded in decisions |

## Your time

| Task | Estimate |
|---|---|
| Approve or amend P12-1 to P12-6 | 10 minutes |
| Step 6, if you want it: stop Ollama when asked, then start it again | 2 minutes |
| The merge and push decision | 5 minutes |

## Risks

- **A retry on a version that changed since its failure.** It might have been withdrawn, superseded or re-chunked. The stage functions already refuse versions that aren't eligible, so `retry` reports their error rather than forcing anything.
- **`EMBEDDING_FAILED` is retryable even when the cause is an invalid vector**, such as NaN (`src/techdocqa/indexing/pipeline.py:104`). A model that returns NaN for a text will do so again, so `retry` would fail again without harm. The classification is left as it is and recorded.
- **A slow but running Ollama**, for example while it updates itself, can miss the 5 s probe and show as `down`. Running `check` again settles it.
- **Log growth.** Neither log rotates. The size is small (IDs and codes only), and the setting turns the new log off.

## Out of scope

- **The web UI (FR-22, P2) and cross-version reuse (FR-05 and FR-11, P2):** skipped by the owner on 2026-11-14.
- Automatic retries inside a run, unless P12-1 is amended.
- Paid-API cost summaries (FR-24 behaviour 4) and any hosted API.
- New URL sources.
- The items Phase 11 did not measure. They stay as recorded in the [Phase 11 report](PHASE_11_STATUS.md#not-measured).
