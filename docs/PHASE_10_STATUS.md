# Phase 10 P1 hybrid search, reranking and full evaluation

Status checkpoint 2026-11-13 on Windows, Python 3.13.3, local Ollama with `qwen3:1.7b` and `nomic-embed-text`, on branch `feat/phase-10`. It follows the [Phase 10 plan](PHASE_10_PLAN.md), whose decisions P10-1 to P10-12 the owner approved on 2026-11-13; the [decisions](DECISIONS.md#phase-10-contracts-2026-11-13) record what implementation settled.

**Result.**
- **Hybrid search (FR-14) and optional reranking (FR-15)** are implemented and tested. Each has its own calibrated refusal gate.
- **The full benchmark** of 50 reviewed questions ran once in all four configurations (FR-19, AC-19.2).
- **Hybrid met the pre-registered benefit rule over vector** (P10-6), **and the owner made it the default mode** for `search` and `ask` on 2026-11-13. `eval` still defaults to the two P0 modes, so the P0 fingerprint does not move.
- **Reranking did not meet the rule**, so it stays off.
- **20 answers were rated by the owner for FR-19.3:** faithful 17 yes, 3 partly, 0 no; relevant 20 of 20 yes.
- **The OpenAI provider demo (P10-10) was withdrawn** by the owner, so TechDocQA stays local-only, and AC-22.4 and C-07's provider switch stay open by owner decision.

The owner gave Fable 5.2 as the full benchmark's reviewer of record. No owner item is open. See [What remains](#what-remains).

## What was added

| Area | What | Where |
|---|---|---|
| Metrics (AC-19.3) | Item-level Precision@K and nDCG@K under `q13-v1`, K = 1, 3, 5. A repeat finds nothing new and earns nothing. | [metrics.py](../src/techdocqa/evaluation/metrics.py) |
| Runner | `eval --mode` runs `bm25`, `vector`, `hybrid` and `hybrid+rerank` in one run, with per-technology tables. It compares candidate with baseline by paired bootstrap (`paired-bootstrap-percentile-v1`: 10,000 resamples, seed 20261113) and applies the P10-6 rule. The P0 fingerprint is unchanged. | [runner.py](../src/techdocqa/evaluation/runner.py) |
| Held-out awareness (P10-8) | Any dataset is compared with `benchmark_smoke.jsonl`. When it holds questions smoke does not, the notes say so, and refusal proposals are shown as descriptive with no configuration section. | runner.py |
| Hybrid search (FR-14) | `rrf-v1` fusion with both ranks, scores and component relevances kept on each result. Each retriever searches to `candidate_depth`. If one retriever fails, the other's results are returned marked `degraded` with the failed retriever's code; if both fail, the search fails. | [search.py](../src/techdocqa/retrieval/search.py) |
| Hybrid gate (P10-3) | `[retrieval.sufficiency.hybrid]` names a gate (`vector`, `bm25`, `either` or `both`) with thresholds per component. Proposals come from smoke, chosen by leave-one-out errors, then margin. A degraded search is judged by the surviving mode's own thresholds. | [sufficiency.py](../src/techdocqa/answering/sufficiency.py) |
| Reranking (FR-15) | Optional and off by default, switched in `[retrieval] rerank` or per request: `--rerank` / `--no-rerank` on `search` and `ask`, and `eval --mode hybrid+rerank`. At most `rerank_max_candidates` candidates are sent. A failure keeps the unreranked order, marked `degraded`. The reranker has its own 0-1 scale (`cross-encoder-sigmoid-v1`) and thresholds. | [rerank.py](../src/techdocqa/retrieval/rerank.py) |
| Cross-encoder (P10-5) | `cross-encoder/ms-marco-MiniLM-L6-v2`, pinned by revision and by the SHA-256 of each file it reads, run as fp32 ONNX on the locked `onnxruntime` with no torch. It uses 4 threads, scores each pair alone and truncates at 512 tokens. A missing or altered file degrades search to the unreranked order. `scripts/fetch_reranker.py` downloads and verifies the files once. | [cross_encoder.py](../src/techdocqa/retrieval/cross_encoder.py), [fetch_reranker.py](../scripts/fetch_reranker.py) |
| Hashed lock (P9-11) | All 142 pins in `requirements.lock.txt` carry their Windows cp313 wheel's SHA-256, so pip runs in hash-checking mode. Phase 10 adds no package. | [requirements.lock.txt](../requirements.lock.txt) |
| Full benchmark (P10-8) | `datasets/benchmark_full.jsonl`: the 30 smoke lines byte for byte, plus 20 new questions (16 answerable, 4 in-domain unanswerable). The review was reported by the owner with no changes; the reviewer of record is Fable 5.2, as the owner directed. It is frozen at SHA-256 `15c3bcb2...e0b0162a`. Of the 50 questions, 14 are unanswerable (28%). | [review log](../datasets/review_log.md#full-benchmark-review-log-phase-10) |
| Answer review (FR-19.3, P10-9) | `eval --answers N --seed S` shuffles the answerable questions once and asks them in order until N have an answer with a citation. Its sheet has Faithful and Relevant columns, and `--record-review` counts both ratings with no pass mark. Phase 8's review is unchanged. | [answers.py](../src/techdocqa/evaluation/answers.py) |

## Runs on the real corpus

All reports are committed under [reports/evaluation](../reports/evaluation). Each records `dirty: true` because `git status` counts the untracked `research_notes/` directory; no tracked file had changed for any run except the two scripted degraded runs. Step 7's code edits began during those runs, after the script had loaded the modules it uses ([decisions](DECISIONS.md#phase-10-contracts-2026-11-13)).

| Run | What | Report |
|---|---|---|
| Smoke, four configurations | Threshold proposals, adopted by the owner: hybrid gate `vector` at 0.858223, reranked at 0.518618 | `eval_a4d00103eb5645a89f93cf78065aecf0` |
| Full benchmark, four configurations, once | P10-6 verdicts, held-out view, gate findings | `eval_b8b8c7dbd9684b848d28ad710cd40d8b` |
| Refusal, `hybrid` | AC-18.1 10 of 10, AC-18.2 18 of 20 | `refusal_fa0ff07673a0407ab32a411053a49a52` |
| Refusal, `hybrid+rerank` | AC-18.1 10 of 10, AC-18.2 18 of 20 | `refusal_62b3e54624284c8c8e18b14da328a873` |
| Degraded `hybrid`, scripted | Embedder failing; BM25's gate; AC-18.1 10 of 10, AC-18.2 19 of 20 | `refusal_25281f684f7a46fcb82f6c197a75356e` |
| Degraded `hybrid+rerank`, scripted | Embedder failing; reranker's gate; AC-18.1 10 of 10, AC-18.2 17 of 20 | `refusal_033417cf118148d0b47cada31c35d4dd` |
| FR-19.3 answers | 20 answers from 24 questions asked, `hybrid`, unreranked; owner's ratings: faithful 17 yes, 3 partly, 0 no; relevant 20 of 20 yes | `answers_014faa565acb49c68956490a1ed2cd55` |

### Full benchmark (AC-19.2)

36 answerable questions, top 5. Search p95 is the nearest-rank 95th percentile of per-question search time over all 50 questions. The per-technology results for all four configurations are in the report's "By technology" table, [eval_b8b8c7db...](../reports/evaluation/eval_b8b8c7dbd9684b848d28ad710cd40d8b.md).

| Configuration | Recall@5 | MRR | nDCG@5 | Precision@5 | Search p95 |
|---|---|---|---|---|---|
| bm25 | 0.815 | 0.708 | 0.699 | 0.217 | 0.051 s |
| vector | 0.884 | 0.757 | 0.739 | 0.239 | 1.917 s |
| hybrid | 0.894 | 0.788 | 0.785 | 0.244 | 1.335 s |
| hybrid+rerank | 0.898 | 0.811 | 0.820 | 0.244 | 3.064 s |

**Measured benefit (P10-6)**, nDCG@5 differences on the 36 answerable questions:

| Comparison | Mean | 95% interval | Better / tied / worse | Verdict |
|---|---|---|---|---|
| hybrid against vector | +0.046 | [+0.009, +0.085] | 12 / 21 / 3 | **Met**: hybrid is now the default mode (owner, 2026-11-13) |
| hybrid+rerank against hybrid | +0.035 | [-0.029, +0.099] | 10 / 21 / 5 | Not met: `rerank` stays false |
| vector against bm25 (descriptive) | +0.040 | [-0.047, +0.129] | 11 / 14 / 11 | - |

**Held-out questions.** The 16 new answerable questions were never used for calibration. On them, nDCG@5 is bm25 0.617, vector 0.692, hybrid 0.731 and hybrid+rerank 0.740, against 0.765, 0.777, 0.828 and 0.884 on smoke. On these questions the order holds for nDCG@5 and MRR but not for Recall@5: vector 0.833 is ahead of hybrid 0.823 and hybrid+rerank 0.802. The reranker's lead over hybrid shrinks from 0.056 on smoke to 0.009.

**Gates on the held-out questions,** with the adopted thresholds and nothing recalibrated:
- **In-domain negatives.** `bm25`, `vector` and `hybrid` refuse all 4. Under the hybrid gate, their top vector relevances fall short of the threshold by 0.0009 to 0.038.
- **Finding: the reranker passes `full-postgresql-05` (pg_dump) at 0.914.** It is passed on a getting-started passage about `PGHOST`, which says nothing about `pg_dump`. Reranking is off by default.
- **Answerable questions.** `vector`, `hybrid` and `hybrid+rerank` pass 15 of 16 and refuse `full-postgresql-02` (`COPY`), although its labeled chunk is retrieved. `bm25`, which degraded hybrid also uses, passes only 7 of 16.
- **Label gap.** `full-kafka-04` scores 0 in every configuration. An unlabeled chunk that supports the answer is ranked second. The benchmark is frozen, so the labels stand.

### Refusal in the new modes (FR-18)

On smoke with the real model, by the Phase 8 method:

| Configuration | Gate | AC-18.1 (target 0.9) | AC-18.2 (target 0.85) |
|---|---|---|---|
| hybrid | vector relevance, 0.858223 | 10 of 10 | 18 of 20 (0.90) |
| hybrid+rerank | reranker, 0.518618 | 10 of 10 | 18 of 20 (0.90) |
| degraded hybrid (scripted) | BM25's Phase 8 thresholds | 10 of 10 | 19 of 20 (0.95) |
| degraded hybrid+rerank (scripted) | reranker over BM25 candidates | 10 of 10 | 17 of 20 (0.85) |

Every unanswerable question was refused at the gate with no chat call. Every answerable question that went unanswered had passed the gate; the model then returned `INSUFFICIENT_CONTEXT` or `NO_VALID_CITATIONS`.

The two degraded runs are scripted checks: only the query embedding failed, while chat stayed the real model. Smoke calibrated every gate here, so these runs show the gates working on their own calibration set. The held-out evidence is in the full run above.

### Answer review (FR-19.3)

- **Sample.** The sample and the top-up rule were fixed in [decisions](DECISIONS.md#phase-10-contracts-2026-11-13) before any answer was generated. The seed is 20261113, and the questions are answered in `hybrid` mode with reranking as configured (off).
- **The run.** It asked 24 questions to get 20 answers with a citation: 11 new questions and 9 from smoke. Of the four without an answer, one was refused at the gate (`full-postgresql-02`) and three were declined by the model.
- **Prompts.** They stayed within the token bound: at most 1,822 tokens, against a bound of 6,418.
- **AC-16.1 is not judged on this run.** Its JSON reports `ac_16_1.met: false` only because the four questions without an answer count as asked.
- **The owner's ratings** (recorded 2026-11-13 as "Project owner"):

  | Rating | Yes | Partly | No |
  |---|---|---|---|
  | Faithful: every claim supported by the cited chunks | 17 | 3 | 0 |
  | Relevant: answers the question | 20 | 0 | 0 |

  All three answers rated partly are on new questions, and each states something its chunk does not support:
  - `full-postgresql-01` invents transaction states.
  - `full-spark-01` adds a vague fallback claim.
  - `full-kafka-03` reverses Kafka's default for unclean leader election.

  P10-9 sets no pass mark, so these are reported as counts. For comparison, Phase 8's AC-16.6 bar of 80% rated supported would be met (85%), but AC-16.6 is not judged on this run.

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| AC-14.1 a chunk found by both retrievers appears once with both ranks | Met | `test_hybrid.py` |
| AC-14.2 hand-computed RRF to 4 decimals | Met | `test_hybrid.py` |
| AC-14.3 vector failing returns BM25 results with `degraded=true` | Met | `test_hybrid.py`; real index with an unreachable embedder (step 2) and the scripted degraded runs |
| AC-14.4 one query, three modes, one interface | Met | `test_hybrid.py` |
| AC-15.1 order follows a mocked reranker's scores | Met | `test_rerank.py` |
| AC-15.2 disabled reranking keeps the input order, truncated | Met | `test_rerank.py` |
| AC-15.3 at most the configured maximum is sent | Met | `test_rerank.py` (call log) |
| AC-15.4 a reranker exception falls back with `degraded=true` | Met | `test_rerank.py`, including altered model files |
| AC-15.5 the report lists hybrid with and without reranking | Met | `test_rerank.py`; full run |
| AC-19.2 four configurations with Precision@K, Recall@K, MRR and nDCG@K | Met | `eval_b8b8c7db...` (243 s, within the time limit) |
| AC-19.3 metric unit tests, now with Precision@K and nDCG@K | Met | `test_evaluation.py` |
| FR-19 full benchmark of at most 50 questions that keeps smoke and is at least 15% unanswerable | Met | `benchmark_full.jsonl`: 50 questions, 28% unanswerable |
| FR-19.3 at least 20 manually evaluated answers | Met: 20 rated by the owner, faithful 17 yes, 3 partly, 0 no; relevant 20 of 20 yes | `answers_014faa56...` |
| FR-18 for hybrid, reranked and degraded hybrid | Met on smoke | refusal runs above |
| AC-22.4 the same `ask` under `openai` and `ollama` | **Open by owner decision** (P10-10 withdrawn) | [decisions](DECISIONS.md#phase-10-contracts-2026-11-13) |
| C-07 configuration-only provider switch with a rebuild | **Open by owner decision**; the provider is still chosen in configuration | - |
| C-06 cost or hardware for ingest plus one full benchmark | Reported below | - |

## Hardware and run times (C-06)

- **Hardware.** A 4-core Intel i7-1165G7 with 11.8 GB of RAM and no GPU. Everything runs locally, so there is no API cost.
- **One full benchmark** in all four configurations took 243 s, with both Ollama models loaded.
- **Indexing** the whole corpus took 548 s in Phase 5: 21 versions and 2,718 chunks, including the private supplement. `enrich` takes 17 to 21 s for all 21 documents (Phase 9).
- **The reranker** adds about 1 s to a search: the median goes from 1.18 s to 2.15 s on the full run. A process's first reranked search loads the model and checks its hashes, and took 3.45 s in the dependency gate.
- **Answers.** With `qwen3:1.7b` they take a median of 11.8 s and a p95 of 19.6 s per question (FR-19.3 run).

## Tests

The full offline suite passed on 2026-11-13, run in groups by `scripts/run_tests.py`, one process each:

| Group | Modules | Result | Time |
|---|---|---|---|
| core | schemas, settings, registry, safety, normalization, segmentation, loaders, ingest, online, chunking | 238 passed, 2 skipped | 136 s |
| retrieval | versioning, indexing, cli, hybrid, rerank | 154 passed | 1,064 s |
| answering | evaluation, generation, citations, sufficiency | 113 passed, 1 skipped | 862 s |
| enrichment | entities, keyphrases, nlp_gold, enrichment, classification, enrichment_eval | 144 passed | 558 s |

That is 649 passed and 3 skipped: the two existing symlink skips and the opt-in live-model test. The reranker tests include the real pinned model, because its files are present.

**Checks after hybrid became the default** (2026-11-13):
- `core` passed again: 238 passed, 2 skipped, in 88.7 s.
- On the real index, `search` without `--mode` ran `hybrid` (`rc_0f2bfab3e618`), not degraded.
- The smoke `eval` still gives the P0 fingerprint `48ce89dc...a3af410`, in 45.7 s, with the same `bm25` and `vector` IDs.
- `scripts/cli_smoke.ps1` passed 9 of 9 with the real models, with `ask` now in hybrid mode. The answer passed the hybrid gate at vector relevance 0.944, and the question after withdrawal was refused at 0.718 with no model call. The script now prints each component's relevance for the hybrid gate.

## What remains

- **Reviewer of record.** The owner gave Fable 5.2 (`claude-fable-5-2`) as the full benchmark's reviewer of record, an AI reviewer where FR-19 intends a person, as in Phase 8. The FR-19.3 answer ratings are recorded as the project owner's.
- **AC-22.4 and C-07's provider switch** stay open by owner decision. The Phase 7 `ChatOpenAI` branch and its mocked tests are unchanged.
- **Findings, with nothing recalibrated:**
  - the reranker's false pass on `full-postgresql-05`;
  - the false refusal of `full-postgresql-02`;
  - the narrow margins of the hybrid gate on the in-domain negatives;
  - the `full-kafka-04` label gap.

  Any change to thresholds or labels would need new held-out questions to judge it.
- **Security chore.** `pip-audit` reports advisories in 6 existing packages (certifi, chromadb, pip, pypdf, setuptools, soupsieve). Most are not reachable here or are mitigated (step 5); they are left to a separate chore.
- **Licence caveat.** The reranker's weights are Apache-2.0, but they were trained on MS MARCO, whose terms describe the data as intended for non-commercial research. The owner accepted this caveat.
- **Deferred (P10-12).** P9-6 secondary categories, and entity and keyphrase boosting.
