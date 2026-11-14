# Phase 11 operational verification and delivery

Status checkpoint 2026-11-14 on Windows, Python 3.13.3, Ollama 0.40.16 with `qwen3:1.7b` and `nomic-embed-text`, on branch `feat/phase-11`. It follows the [Phase 11 plan](PHASE_11_PLAN.md), whose decisions P11-1 to P11-12 the owner approved on 2026-11-14. The [decisions](DECISIONS.md#phase-11-contracts-2026-11-14) record each run in full.

**This phase was closed early, and it is not a release claim.**
- **The shutdown.** The whole-corpus ingestion run started at 10:08 local time on 2026-11-14. Windows rebooted at 10:14 after an unclean shutdown (Kernel-Power event 41). The owner reports that the laptop shut itself down from heat.
- **The owner's instruction.** *"skip next phase or QA runs as long as the project runs."*
- **What follows.**
  - The remaining runs are recorded below as **not measured**, never as met.
  - Two documentation items, which are not runs, are recorded as **not done**.
  - Phase 12 is not started.

**Result.**
- **Search latency (NFR-02) is met in all four configurations,** after one fix that preserves results. Reusing the verified query embedder took the hybrid p95 from 1.954 s to 0.145 s. The four-configuration full-benchmark fingerprint is the same before and after the fix.
- **The headroom for search (NFR-01) holds.** On the whole index of 2,735 chunks, 3.35 times the reference, every p95 stays under its target.
- **QA latency (NFR-03) is met:** a p95 of 22.0 s against 60 s.
- **Ingestion (NFR-04) is met for the reference:** 208.5 s from empty against 30 min. The whole corpus was not timed.
- **The secret and private-text scan (AC-23.4) is clean,** and the two reachable dependency advisories are fixed.
- **Every run now records** the Ollama version, where each model runs, the hardware and the power state (NFR-05).
- **The project runs after the shutdown.** The checks that load no model all passed (see [below](#checks-after-the-shutdown)).

## Requirements

Statuses are taken as measured, and none is upgraded. "Not measured" means the run was skipped on the owner's instruction of 2026-11-14. "Not done" marks documentation that was not started; the instruction did not cover it.

| ID | Target | Evidence | Status |
|---|---|---|---|
| NFR-01 | 2x headroom without changes | Search on the whole index, 3.35x the reference by chunks and 1.78x by bytes (`latency_2fef1c3a...`) | **Met for search.** Ingestion at the whole corpus: not measured |
| NFR-02 | p95 at most 1 s, or 5 s with reranking | Evaluation scope (`latency_6a9e5bcb...`): bm25 0.044 s, vector 0.148 s, hybrid 0.145 s, hybrid+rerank 1.090 s. Whole index (`latency_2fef1c3a...`): 0.041, 0.129, 0.134, 0.841 s | **Met**, after fix `c6d6e2f` under P11-2. As first measured, vector (1.155 s) and hybrid (1.954 s) missed |
| NFR-03 | p95 at most 60 s, local | 35 questions reached generation: p95 22.0 s, maximum 27.8 s, 0 timeouts (`latency_caca243a...`) | **Met.** The OpenAI half is not applicable |
| NFR-04 | At most 30 min, local | Reference from empty: 208.5 s to searchable (`ingestion_0b1f8645...`) | **Met for the reference.** Whole corpus: not measured. The OpenAI half is not applicable |
| NFR-05 | Pinned, and recorded with each run | 142 hashed pins. Each run records the Ollama version, model placement, hardware, power state and 13 library versions | **Met** |
| NFR-06 | Identical retrieval across runs | Four-configuration fingerprint `545c0d35...fe650` 3 times in Phase 11, and the smoke P0 fingerprint `48ce89dc...a3af410` at every check | **Repeat met.** `index --rebuild`: not repeated since Phase 5 |
| NFR-07 | Clean-machine setup in a few commands | [`deployment/local_setup.md`](../deployment/local_setup.md) rewritten to the current state (`a40b0f6`) | **Not measured:** the clean-clone setup was not run |
| NFR-08 | A fully local mode | Local is the only mode. The setup guide lists everything that touches the network | **Met.** The OpenAI disclosure is not applicable |
| NFR-09 | A recorded budget | No API spend, by owner decision | **Met as zero API spend** |
| NFR-10 | Tests for each FR's ACs, and a traceability matrix | Per-phase slices in [traceability](requirements_traceability.md) | **Not done:** the consolidated matrix (P11-10) was not built |
| NFR-11 | Separate, replaceable components | Separate modules | **Not reviewed:** the component map (P11-10) was not built |
| AC-23.4 | No secret in logs, output or files | 0 key-shaped strings in 188 files, 65 commits and 14 run outputs. 0 shared runs of the private supplement | **Met at `3e6df0e`.** The later commits, which add reports of counts and timings and documents, have not been scanned |
| DS-04 | Corpus and model licences | [Licences](#licences) | **Met for the public reference.** The private supplement's permissions are unverified, as recorded since Phase 5 |
| C-06 | Hardware for one ingest plus one full benchmark | [Hardware and run times](#hardware-and-run-times-c-06) | **Met as a local hardware statement** |
| C-07, AC-22.4 | Provider switch by configuration | None | **Open by owner decision** (local-only) |

## Hardware and run times (C-06)

- **Machine.**
  - Intel Core i7-1165G7 with 8 logical CPUs and 11.8 GB of RAM.
  - Intel Iris Xe graphics, plus an NVIDIA GeForce MX450 with 2 GB.
  - Windows 11, Python 3.13.3, Ollama 0.40.16.
- **Where the models run.**
  - `nomic-embed-text` runs 100% on the GPU.
  - `qwen3:1.7b` runs 78% on the CPU and 22% on the GPU.
  - The cross-encoder runs on the CPU through `onnxruntime`.
- **Disk.**
  - `data/` takes 223 MB, the reranker files included.
  - Ollama's model folder takes 1.6 GB, for every installed model.
- **One ingest plus one full benchmark takes about 4.7 minutes.**
  - Ingesting the reference from empty takes 208.5 s, plus 7.8 s for `enrich`.
  - The full benchmark in four configurations takes 64 s.
- **Limits of this laptop.**
  - Long runs heat it. It shut itself down during the whole-corpus ingestion run on 2026-11-14.
  - On battery, timings are invalid: two reranked searches took 84.0 s and 26.2 s instead of about 0.8 s.
  - With the chat model loaded, free RAM fell to 0.3 GB.
  - Sustained runs need AC power, cooling, and no other heavy process.

## Licences

| Item | Licence | Checked against |
|---|---|---|
| Apache Airflow, 4 documents | Apache-2.0 | Manifest, review status `verified` |
| Apache Kafka, 4 documents | Apache-2.0 | Manifest, `verified` |
| Apache Spark, 5 documents | Apache-2.0 | Manifest, `verified` |
| PostgreSQL, 7 documents | PostgreSQL Licence | Manifest, `verified` |
| Designing Data-Intensive Applications | Permissions unverified | Private supplement, outside the public reference |
| `qwen3:1.7b` | Apache-2.0 | The licence layer of the installed Ollama model |
| `nomic-embed-text:latest` | Apache-2.0 | The licence layer of the installed Ollama model |
| `cross-encoder/ms-marco-MiniLM-L6-v2` at `233902d` | Apache-2.0 | The pinned model card in `data/models`. Trained on MS MARCO, whose terms describe the data as intended for non-commercial research; the owner accepted this caveat in Phase 10 |

## Checks after the shutdown

These checks load no model. They ran on battery with 1.9 GB of RAM free, and Ollama was not running.

| Check | Result |
|---|---|
| `techdocqa config-check` | Exit 0, configuration valid |
| `techdocqa list` | Exit 0: 21 indexed documents, plus the Spark Data Sources overview [rejected in corpus review](REFERENCE_CORPUS_STATUS.md#rejections-and-duplicate-checks) |
| `techdocqa search "How does a B-tree index work?" --mode bm25` | Exit 0. The first result is the PostgreSQL B-tree section |
| `datasets/verify_corpus.py` | Passed: 21 documents, 2,735 chunks, 816 of them in the reference, 0 duplicates |
| Chroma collection count | 2,735 entries |
| Vector query with a stored embedding, which loads the HNSW index | The same chunk is at rank 1, with distance 0 |
| `git status` | Clean |

Hybrid search, the default, and `ask` were not run after the shutdown. Both need Ollama. The last hybrid searches and answers ran successfully on the same day, before the shutdown, in the latency runs above.

## Tests

No test was run in this close-out.
- Phase 11 changed code in `c04fd7c`, `1aa05fe` and `c6d6e2f`, and added `tests/test_profiling.py` and `tests/test_scans.py`.
- The `core` group's pass is recorded in step 2.
- **The full grouped suite has not run since those changes.** The last full record is Phase 10's: 649 passed and 3 skipped.

## Not measured

Each item is the owner's to accept or to run later, one at a time, on AC power, with the laptop cool.

| Item | Requirement | How to run it |
|---|---|---|
| Whole-corpus ingestion timing | NFR-04, NFR-01 | `.venv\Scripts\python.exe scripts\time_ingestion.py --scope all` |
| Rebuild with an identical top 5 and 0 model calls | NFR-06 | Back up `data\index\chroma`. Then run `verify_index.py --snapshot FILE`, `techdocqa index --rebuild` and `verify_index.py --compare FILE` |
| Clean-clone setup | NFR-07 | The P11-6 steps in the plan |
| Full grouped suite, about 44 minutes in Phase 10 | NFR-10 | `.venv\Scripts\python.exe scripts\run_tests.py`, or one group at a time, such as `scripts\run_tests.py core` |
| CLI workflow with the real models | Regression | `scripts\cli_smoke.ps1` |
| Secret scan of the commits after `3e6df0e` | AC-23.4 | `.venv\Scripts\python.exe scripts\scan_secrets.py` |

Not done, and not covered by the instruction: the consolidated per-AC matrix and the NFR-11 component map (P11-10). Both are documentation only, with no machine load.

`.tmp/p11-ingest` still holds the interrupted run's copies of the 21 source files, the private supplement included. The folder is ignored by git, and deleting it is the owner's call.

## Release decision

This is for the owner to make; this report does not declare it. Under P11-12, delivery is local only.
- **Accept the phase as closed,** with the items above not measured, and merge `feat/phase-11` into `main` locally.
- **Or keep the branch open,** and run the items above later.

Nothing has been pushed.
