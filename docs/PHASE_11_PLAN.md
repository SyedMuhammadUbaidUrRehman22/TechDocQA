# Phase 11 plan: operational verification and delivery

Status: **proposed and approved 2026-11-14.** The owner chose the recommended option on the four owner questions (P11-2, P11-3, P11-8 and P11-12). The other decisions stand as proposed, under the owner's instruction to proceed. They are recorded as [Phase 11 contracts](DECISIONS.md#phase-11-contracts-2026-11-14). It covers [roadmap Phase 11](IMPLEMENTATION_ROADMAP.md#phase-11--required-operational-verification-and-delivery):
- measuring NFR-01 to NFR-11;
- C-06 and the cumulative P0/P1 regression;
- a clean-machine setup;
- secret, privacy and licence checks;
- the delivery documents.

It follows the owner's decision of 2026-11-13 that TechDocQA is local-only, so **every OpenAI step is excluded** ([decisions](DECISIONS.md#phase-10-contracts-2026-11-13)). Sources: [Revision 3 requirements](../TechDocQA_Requirements_v2.md) section 6, the [SDD](TECHDOCQA_SDD.md) section 2 and the [Phase 10 report](PHASE_10_STATUS.md).

## Entry gate

Phase 10 is complete and merged into `main` (`19c838b`, pushed). A baseline check ran on 2026-11-14 before this plan was written:

- **Ollama has updated itself to 0.40.16.** Earlier phases verified the configuration on 0.40.10 and 0.40.13, and no run records the server version.
- **The smoke `eval` reproduces the P0 fingerprint** `48ce89dc...a3af410`, with the same `bm25` and `vector` configuration IDs, in 35.8 s (`eval_7b0630ea...`, report kept out of the repository). The fingerprint hashes every question's scores and relevances, not only its ranks, so the update did not change the embeddings. Hybrid, which is built from the same two components, is unaffected.
- **`datasets/verify_index.py --compare`** against the Phase 9 snapshot passed: the top 5 is identical in both modes, 8 of 8 identifiers are at rank 1, and the index holds 2,735 entries.

## Local-only scope

| Requirement | Its OpenAI part | Phase 11 treatment |
|---|---|---|
| NFR-03 | p95 at most 15 s with the OpenAI API | Not applicable, local-only by owner decision; the 60 s local target is measured |
| NFR-04 | At most 15 min with OpenAI embeddings | Not applicable; the 30 min local target is measured |
| NFR-08 | State that chunk text and questions go to an external API | Not applicable. The fully local mode is the only mode, and the documentation lists everything that touches the network (P11-7) |
| NFR-09, C-06 | Expected API cost | No API cost; the budget is recorded as no API spend, and C-06 is met as a hardware statement (P11-9) |
| C-07, AC-22.4 | Switch between OpenAI and Ollama by configuration only | **Open by owner decision.** No local substitute is built, and the Phase 7 `ChatOpenAI` branch and its mocked tests stay as they are |

## Invariants

1. **No retrieval result moves and nothing is recalibrated.** The P0 fingerprint, every mode's configuration IDs, and the adopted thresholds stay as they are. Full-benchmark reruns are for latency and determinism only.
2. **No NFR target is weakened.** A miss is recorded as a miss. Amending a target is the owner's decision, made explicitly.
3. **Timing runs that write go to a scratch `data_directory`, never to `data/`.** Re-registering in place would break the manifest's version IDs.
4. **Tracked reports from any run that touches the private supplement hold counts and timings only**, never its text. `reports/` is tracked and pushed.

## What already exists

Chunk counts below are taken from the registry: 816 chunks in the 20-document public reference, and 2,735 index entries (2,727 distinct vectors) with the private supplement.

| Requirement | Target | Evidence so far | Gap |
|---|---|---|---|
| NFR-01 | Headroom of 2x without changes | The index already holds 2,735 chunks: 3.35x the public reference by chunks, 1.78x by bytes | Never measured as headroom |
| NFR-02 | p95 at most 1 s without reranking, 5 s with it | Phase 10 full run: bm25 0.051 s, vector 1.917 s, hybrid 1.335 s, hybrid+rerank 3.064 s. Smoke on 2026-11-14: vector 1.332 s | No stage timings, no fixed procedure. As measured, the vector and hybrid modes miss |
| NFR-03 | p95 at most 60 s, local on CPU, with retrieval and generation reported separately | FR-19.3 run: median 11.8 s, p95 19.6 s; `QALatency` already splits the stages | No defined population |
| NFR-04 | At most 30 min, local | Phase 5: `index` took 548 s for the whole local corpus, from cached chunks | Never timed end to end from an empty registry |
| NFR-05 | Pinned and recorded with each run | Hashed lock with 142 pins; runs record Python, the platform, 8 library versions and the embedding model's digest | Not recorded: the Ollama server version, `onnxruntime`, `tokenizers`, the hardware |
| NFR-06 | Identical retrieval across runs | AC-19.4; the Phase 5 restart and rebuild; the entry gate above | No rebuild since Phase 5; the hybrid and reranked modes have not been repeated |
| NFR-07 | A clean-machine setup in a few commands | README and `deployment/local_setup.md` | Never run from a clean clone. `local_setup.md` is out of date: it runs the suite as one `pytest` process and says the models are unset |
| NFR-08 | A fully local mode | Ollama and the local cross-encoder only | No single statement of what touches the network |
| NFR-09 | A recorded budget | None | None set |
| NFR-10 | Tests for each FR's ACs, and a traceability matrix | Per-phase slices in [traceability](requirements_traceability.md) | No consolidated matrix |
| NFR-11 | Separate, replaceable components | Separate modules | Not reviewed against the requirement's list |
| AC-23.4 | No secret in logs, output or files | A test with a runtime secret (Phase 7) | No scan of the history, reports or `data/logs` |
| C-06 | Hardware for ingest plus one full benchmark | Phase 5 records an NVIDIA MX450 with 2 GB; Phase 10 says no GPU | Conflicting, and which processor Ollama uses was never recorded |

Two observations from reading the code, not yet measured:
- Each vector or hybrid search builds a new embedder, whose check of the pinned digest lists Ollama's installed models, and opens a new Chroma client. How much of the latency this accounts for is unknown.
- `research_notes/` is untracked, so every run records `dirty: true`.

## Decisions to approve before measuring

| ID | Decision | Recommendation | Why, and the alternative |
|---|---|---|---|
| P11-1 | Profiling procedure (NFR-02, NFR-03) | **Machine state, recorded per run:** free RAM, AC power, the Ollama version, and the PROCESSOR column of `ollama ps` for each loaded model. No test run or other heavy process may overlap.<br>**Retrieval:** the in-process `search()` call, timed over all 50 full-benchmark queries in each of `bm25`, `vector`, `hybrid` and `hybrid+rerank`, on the evaluation scope. One uncounted warm-up per mode, then 3 passes. The p95 is nearest-rank over the 150 timings per mode. A fresh process's cold first query and the CLI's process start are reported separately, outside the p95.<br>**Stage timings:** a script wraps the stage functions (building the embedder, embedding the query, opening the store, the vector search, BM25 and its index build, the stored relevances, the rerank). Production code, schemas, IDs and fingerprints do not change.<br>**QA:** the 36 answerable full-benchmark questions in the default `hybrid` mode, one pass. The p95 counts **only questions that reach generation**; gate refusals, which make no model call, are reported apart. A timed-out call counts as over the target, never dropped: the timeout is 60 s, equal to the target. | Fixes the procedure the roadmap requires before any number exists. Wrapping the functions keeps the measurement out of the product. Alternative: stage timers in `search.py`, which would add a field to the search schema. |
| P11-2 | If NFR-02 misses | **Owner's choice: fixes that preserve results only.** Measure as-is first. Then allow only fixes that preserve results, such as reusing one verified embedder and one Chroma client per process, or keeping the embedding model loaded. Each must be proved by identical P0 and four-configuration full-benchmark fingerprints. Anything that changes results, or an amended target, comes back to the owner. | A result-changing fix, such as a smaller embedding model, would invalidate the Phase 10 held-out evidence and the calibrations. Reusing the embedder means a model swapped mid-process is caught at the next process start, not the next query. |
| P11-3 | Headroom (NFR-01) | **Owner's choice: the whole local index,** 2,735 chunks or 3.35x the reference by chunks, for search latency (P11-1 unscoped) and for ingestion (P11-4), with no configuration change. Tracked reports hold counts and timings only. | Needs no new data. It is 1.78x by bytes, but embedding and search time scale with chunks. Alternative: a synthetic 2x corpus, which embeds repeated text from cache and so understates the time. |
| P11-4 | Ingestion timing (NFR-04) | A scratch `data_directory` under `.tmp/` with its own configuration file, fed copies of the frozen bytes: the local files, plus the HTML snapshots as local `.html` files, which use the same `extract_html`. Time `ingest`, `process`, `chunk` and `index` one by one, with an empty embedding cache. Assert that the embedding calls equal the distinct chunk texts, since a run with no calls is a cache hit, not a timing. Check 816 chunks and compare each `content_hash` with the manifest, reporting any difference rather than fixing it. Time `enrich` separately. Repeat with all 21 documents for P11-3. Delete the scratch data afterwards. | Measures the real path from empty without touching the frozen registry. Re-fetching the 13 pages online would time the network and could pick up changed pages. |
| P11-5 | Determinism and run records (NFR-05, NFR-06) | Add the Ollama server version, `onnxruntime`, `tokenizers` and a hardware summary to every run's environment, outside the fingerprint, with a test that the fingerprint does not move. Run the full benchmark in all four configurations twice and require identical fingerprints. Back up `data/index/chroma`, run `index --rebuild`, and require identical top 5 and 0 model calls. | Ollama updates itself, so its version must be visible in every run. The repeats cover the hybrid and reranked modes, which Phase 10 ran only once. |
| P11-6 | Clean setup (NFR-07) | `git clone` the repository into a scratch folder, not a copy of the tree. Then a fresh `py -3.13` venv, `pip install --no-cache-dir -r requirements.lock.txt`, the editable install, `config-check`, the grouped tests and `scripts/cli_smoke.ps1` against the installed models. Tests that need `data/` or the reranker files must skip, not fail; any that fail are fixed. Record what was downloaded, and claim only Windows with Python 3.13. | A clone has no ignored `data/`, which is what a new user gets. A real second machine is not available. |
| P11-7 | Secret, privacy and licence checks (AC-23.4, NFR-08, DS-04) | **Secrets:** a scripted scan, with no new dependency, of the tracked files, the full git history, `reports/` and `data/logs` for key-shaped strings (OpenAI, Hugging Face, GitHub, AWS, private keys, `.env` content). Every hit is reviewed by hand.<br>**Private supplement:** check that no 200-character window of any of its chunks appears in a tracked file or in the history, printing counts only.<br>**Network:** document what touches the network: `ingest --source` (the official documentation sites only), `pip install`, `ollama pull`, `scripts/fetch_reranker.py` (Hugging Face) and Ollama's own updater. `index`, `search`, `ask` and `eval` contact only `127.0.0.1`.<br>**Licences:** one table for the corpus (from the manifest), the three models, looked up rather than assumed, and the reranker's MS MARCO caveat. | AC-23.4 asks for a system-wide check, and the private supplement makes up 70% of the index. |
| P11-8 | Dependency advisories | **Owner's choice: upgrade the two that are reachable,** each by patch release: `pypdf` to 6.21.4 (crafted PDFs) and `certifi` to 2026.10.18 (online ingestion). Rehash the lock, and require `verify_corpus.py` (normalized text unchanged), the tests and the fingerprints to pass. Document the other four: Chroma's server-side advisories, `pip` (hash-checking mode), `soupsieve` (the one selector has no descendant combinator) and `setuptools` (build only). | A release should not ship reachable advisories without a reason. A `pypdf` change that moved extracted text would be reverted and recorded. |
| P11-9 | Cost and budget (C-06, NFR-09) | Record the budget as no API spend, by owner decision. The hardware statement comes from the measured runs: CPU, RAM, GPU, which processor Ollama used per model, disk use of `data/` and the models, and the wall time of one ingest plus one full benchmark. | Meets C-06 as its local alternative, and NFR-09's budget as zero API spend |
| P11-10 | Consolidated acceptance matrix (NFR-10, NFR-11) | One table in traceability covering every AC of FR-01 to FR-23, plus NFR-01 to NFR-11, C-01 to C-07 and DS-01 to DS-06. Each row has its evidence link and a status taken as recorded, never upgraded: met, met at the point estimate, met with a recorded deviation (such as an AI reviewer), not met, open by owner decision, or not applicable (local-only). FR-24 and the P2 items are listed as not selected. For NFR-11, a table maps each named component to its module and framework abstraction. | AC-08.3 stays not met, and the AI-reviewer deviations stay visible |
| P11-11 | Run hygiene | Add `research_notes/` to `.git/info/exclude`. The change is local, commits nothing and leaves the folder untouched, so formal runs record `dirty: false`. | Phase 10's reports all say `dirty: true` for this reason alone |
| P11-12 | Delivery | **Owner's choice: local only.** Commits go on `feat/phase-11` and are merged into `main` locally; nothing is pushed until the owner says so. The report presents the release decision to the owner rather than declaring it. | Pushing, opening a PR and tagging are outward-facing |

## Pre-registration

Fixed before any Phase 11 measurement:
- the P11-1 procedure;
- the P11-2 miss policy;
- the P11-3 headroom definition.

The proof that a fix preserves results is identical fingerprints before and after it: the smoke P0 fingerprint, and the full benchmark's four-configuration fingerprint, which includes every score and relevance.

## Work sequence

Each step ends with its offline tests passing, and a new test module goes into `GROUPS` in `scripts/run_tests.py`.

| Step | Work | Output and check |
|---|---|---|
| 0 | Approve or amend P11-1 to P11-12 | Recorded in [decisions](DECISIONS.md) as Phase 11 contracts |
| 1 | Run hygiene (P11-11); the run-environment additions (P11-5); the profiling script with its stage wrappers | Fingerprint unchanged; tests |
| 2 | Dependencies (P11-8), so every later step runs on the final lock | `pip-audit` rerun; `verify_corpus.py`; fingerprints |
| 3 | Retrieval latency on the evaluation scope and on the whole index (NFR-02, NFR-01) | A latency report with stage timings and a verdict per mode |
| 4 | Only if NFR-02 misses: diagnose from the stage timings, then apply fixes under P11-2 and measure again | Fingerprints identical, or the question goes to the owner |
| 5 | QA latency (NFR-03) | p95 over the questions that reach generation, retrieval and generation apart |
| 6 | Ingestion timing in scratch, for the reference and for all 21 documents (NFR-04, NFR-01) | Stage times, embedding-call count, hash comparison |
| 7 | Determinism: the full benchmark twice, then the rebuild (NFR-06) | Identical fingerprints and top 5; 0 model calls |
| 8 | Clean-clone setup (NFR-07) | The steps that ran and what was downloaded |
| 9 | Scans and statements (AC-23.4, NFR-08, DS-04, C-06, NFR-09) | Scan results, network and licence tables, hardware statement |
| 10 | Documents: `deployment/local_setup.md` rewritten to the current state, stale README rows replaced, the consolidated matrix, the Phase 11 report and the roadmap. The full offline suite in groups. | `docs/PHASE_11_STATUS.md` |
| 11 | The release decision to the owner, then delivery under P11-12 | Recorded in decisions |

## Your time

| Task | Estimate |
|---|---|
| Approve or amend P11-1 to P11-12 | 15 to 20 minutes |
| Close other apps during the measurement runs, steps 3 to 7: about 1.5 hours of machine time, some of it unattended | - |
| Decide on any NFR-02 fix that would change results, if one is needed | 15 minutes |
| The release decision | 10 minutes |

## Risks

- **Memory.** The machine has 11.8 GB of RAM, and between 0.3 and 2.2 GB was free on 2026-11-14 with other apps open. A run under swap is not a valid measurement, so each run records free RAM, and a run that started short of memory is repeated.
- **Ollama updates itself.** A future update could change the embeddings. The entry gate showed this one did not. Recording the version makes any change visible; turning off the updater is the owner's choice and outside the project.
- **NFR-02 will most likely miss as measured** for vector and hybrid search. The stage timings decide whether a fix that preserves results exists.
- **Laptop variance.** Thermal limits and the power plan move timings, so AC power is recorded and the p95 uses repeated passes.
- **A `pypdf` upgrade could move extracted text.** `verify_corpus.py` must pass; otherwise the upgrade is reverted and the advisory documented.

## Out of scope

- OpenAI or any other hosted API, and any local substitute for C-07.
- FR-24 and the other P2 items (Phase 12).
- The Phase 10 findings on thresholds and labels, which would need new held-out questions.
- Further AC-08.3 work, and any recalibration.
