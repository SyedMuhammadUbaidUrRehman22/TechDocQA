# Phase 10 plan: P1 hybrid search, reranking, full evaluation and provider demonstration

Status: **proposed and approved 2026-11-13.** P10-1 to P10-12 are recorded as [Phase 10 contracts](DECISIONS.md#phase-10-contracts-2026-11-13). It covers roadmap Phase 10: FR-14 hybrid retrieval, FR-15 reranking, FR-19 full evaluation, the FR-22 and C-07 provider demonstration, and FR-18 recalibration for the new modes. Sources: [Revision 3 requirements](../TechDocQA_Requirements_v2.md), [roadmap](IMPLEMENTATION_ROADMAP.md#phase-10--p1-hybrid-reranking-full-evaluation-and-provider-demonstration), [SDD](TECHDOCQA_SDD.md) sections 10 and 13, [decisions](DECISIONS.md) D-11, D-12, D-15, Q-07, Q-08 and Q-13, and the [Phase 8](PHASE_8_STATUS.md) and [Phase 9](PHASE_9_STATUS.md) reports.

## Entry gate

The roadmap puts Phase 10 after Phases 8 and 9. Both are complete: the P0 release gate passed on 2026-11-07, and the owner closed Phase 9 on 2026-11-13 ([decisions](DECISIONS.md#phase-9-completion-2026-11-12)). D-11 and D-12 were proposed in the approval package and are not yet approved. The roadmap also requires the reranker model, and its download, to be explicitly authorized at this stage.

## Invariants

Phase 10 adds modes; it must not move the existing ones.

1. **BM25 and vector search are unchanged.** Hybrid needs 20 BM25 candidates, but `bm25_results` now fetches only `top_k`, so that path will be refactored. These checks prove nothing moved:
   - The smoke `eval` for `bm25` and `vector` gives the baseline `results_fingerprint` `48ce89dc...a3af410`.
   - `datasets/verify_index.py --compare` reproduces the stored top 5.
   - Each mode's `scoring_config_id` and `retrieval_config_id` stay the same: RRF `k`, weights and reranker identity enter only the IDs of the new modes.
2. **QA defaults are unchanged** until the owner approves a change: `mode = "vector"` and `rerank = false`. The Phase 8 thresholds and their calibration run stay valid.
3. **Enrichment is untouched.** No entity or keyphrase boosting (P9-10); keyphrases still do not enter BM25 (P9-5).

## What already exists

| Piece | State | Use in Phase 10 |
|---|---|---|
| BM25 and vector search | `retrieval/search.py`, registry-gated, each returning `ranks`, `scores` and a per-mode 0-1 `relevance` | Hybrid runs both with the same filters. `hybrid` and `rerank` now raise `MODE_NOT_AVAILABLE`. |
| Configuration | `[retrieval]` already has `candidate_depth = 20`, `rrf_k = 60`, `rerank = false`, `rerank_max_candidates = 20` | Requirement defaults are in place |
| FR-18 gate | Per-mode thresholds bound to a `scoring_config_id`; a stale or missing calibration skips the gate and warns `SUFFICIENCY_CALIBRATION_STALE` or `SUFFICIENCY_NOT_CALIBRATED` | The new modes need their own scale and thresholds (Q-07) |
| Evaluation | `eval` with stable anchors, item-level Recall@K and MRR under metric policy `q13-v1`, threshold proposals by `balanced-accuracy-midpoint-v1`, fingerprints | Add Precision@K and nDCG@K, which `q13-v1` already defines (SDD section 13), plus the four configurations and per-technology tables |
| Smoke benchmark | 30 reviewed questions: 20 answerable, 5 per technology (14 factual, 10 how-to, 6 identifier), and 10 unanswerable, all about other technologies | Kept as a subset of the full set; the only calibration data |
| Answer review | `eval --answers N` writes a review sheet; `eval --record-review` judges it (Phase 8) | Reused for the 20 rated answers |
| OpenAI chat | `ChatOpenAI` branch wired, `LLM_CREDENTIALS_MISSING` and `PROVIDER_NOT_INSTALLED` handled; `langchain-openai` not installed; no `OPENAI_API_KEY` set | The demo needs the package, a key and three code gaps (P10-10) |
| Runtime | 4-core i7-1165G7, 11.8 GB RAM, often about 3 GB free with Ollama loaded; `onnxruntime` 1.31.1, `tokenizers` and `huggingface_hub` already installed with Chroma; no torch | A CPU reranker without torch may be possible; the gate checks it |
| Index | 2,735 chunks: 816 public, 1,919 from the private DDIA supplement | DDIA must never reach an external provider (P10-10) |

## Acceptance targets

| Criterion | Target | Planned evidence |
|---|---|---|
| AC-14.1 | A chunk found by both retrievers appears once, with both ranks | Test |
| AC-14.2 | A hand-computed RRF example of 3 chunks matches to 4 decimals | Test |
| AC-14.3 | With vector failing, hybrid returns BM25 results with `degraded=true` | Test, and a real run with Ollama stopped |
| AC-14.4 | One query, three modes, one interface | Test and CLI |
| AC-15.1 to AC-15.4 | Order by a mocked reranker's scores; disabled gives the input order truncated; at most the maximum sent (call log); an exception falls back with `degraded=true` | Tests with a mocked reranker |
| AC-15.5 | The FR-19 report lists hybrid with and without reranking | Full-benchmark report |
| AC-19.2 | A full run shows the four configurations with Precision@K, Recall@K, MRR and nDCG@K | `eval` on the full benchmark |
| AC-19.3 | Metric functions pass hand-computed tests | Tests for the new metrics |
| FR-19.3 | Faithfulness and answer relevance on at least 20 answers | Rated review sheet (P10-9) |
| FR-18 for new modes | Thresholds for hybrid, hybrid with reranking and degraded hybrid, calibrated on smoke and recorded; AC-18.1 and AC-18.2 checked in each | `eval` proposals, then `eval --refusal` with the real model |
| AC-22.4, C-07 | The same `ask` under Ollama and OpenAI by configuration only, rebuilding if the embedding model changes | Demo log (P10-10) |
| C-06 | Approximate cost or hardware for ingest plus one full benchmark | Report |

## Decisions to approve before coding

| ID | Decision | Recommendation | Why, and the alternative |
|---|---|---|---|
| P10-1 | Fusion (D-11, Q-08) | **A small tested RRF function, `rrf-v1`**: `score(c) = Σ w_r / (k + rank_r(c))` over the retrievers that return `c`. Defaults are 20 candidates per retriever with the same filters, `k = 60`, `w_r = 1`, and top-k 5. With equal weights, this is FR-14's formula exactly. Duplicates are merged by `chunk_id`, keeping each retriever's rank, raw score and relevance. Ties go to `chunk_id`. Weights are configurable, and every value enters the hybrid `retrieval_config_id`. | FR-14 allows a custom RRF function. LangChain's `EnsembleRetriever` keeps no per-retriever ranks and has no degraded path, and both retrievers here are registry-gated functions, not plain LangChain retrievers. |
| P10-2 | Degraded hybrid | One retriever raising an error gives the other's results, `degraded=true` and the error code as `degradation_reason`. Both failing is a standard search error, never empty evidence (SDD section 10). An empty result, such as no indexed version, is not a failure. | As FR-14.4 and the SDD specify |
| P10-3 | Hybrid evidence scale (Q-07, FR-18) | An RRF score reflects only rank: an out-of-domain query's top chunk scores as high as a good one's, so RRF cannot gate. **Every fused result carries both component relevances**, computed for every fused chunk, not only where it ranked: vector relevance from the stored vector, and BM25 relevance from the lexical index. Four candidate gates, each with thresholds proposed on smoke by `balanced-accuracy-midpoint-v1`: G1, vector relevance; G2, BM25 relevance; G3, either one passes on its scale; G4, both pass. **Selection rule, fixed now:** fewest leave-one-out errors, then the largest margin, then G1. Degraded hybrid uses the surviving mode's own calibrated thresholds on its own relevance. | Keeps every threshold on a defined 0-1 scale and fixes the selection before any hybrid result exists. Alternative: normalize RRF by its maximum, which is query-independent and so cannot refuse. |
| P10-4 | Reranker evidence scale | The cross-encoder's raw score is mapped to 0-1 by a logistic function (`cross-encoder-sigmoid-v1`), with its own thresholds calibrated on smoke. They are bound to a `scoring_config_id` that hashes the model revision, the file hashes, the candidate maximum and the truncation rule. A reranker failure keeps the pre-rerank order with `degraded=true`, and the hybrid gate applies. | FR-18.1 names "the reranker score if enabled"; a transform with its own ID keeps Q-07 intact |
| P10-5 | Reranker (D-12) | **A local cross-encoder, off by default**: at most 20 candidates, top-k 5, switchable per request (`--rerank`) and by configuration, behind one reranker interface that tests mock. The model is chosen at a **dependency gate** in a scratch environment, in this order of preference: (1) a small English MS MARCO-class cross-encoder on the installed `onnxruntime` and `tokenizers`, with no torch; (2) the same model through a LangChain reranker integration, if that adds no heavy dependency (`langchain-community`, which the BM25 path uses, warns that it is being sunset); (3) a larger reranker only if it fits the latency limit. No LLM reranker. | Gate criteria, all recorded: the licence files of the package and the model weights (YAKE's metadata and file disagreed); a pinned model revision and the SHA-256 of every file; one authorized download, then offline use; identical scores over 3 runs; an explicit truncation rule for 1,000-character chunks plus the query; CPU latency for 20 candidates within NFR-02's 5 s with retrieval; memory with Ollama loaded; `pip-audit`. A failed gate falls back to the next option and is recorded. |
| P10-6 | When reranking or hybrid may become a default | Fixed before any full run: hybrid with reranking shows a **measured benefit** over hybrid when the paired per-question difference in nDCG@5 on the full benchmark's answerable questions has a 95% bootstrap interval above 0 (10,000 resamples, fixed seed) and the p95 search latency is within 5 s. The same rule applies to hybrid over vector. Meeting the rule makes the change eligible; adopting it is the owner's decision. | FR-15 keeps reranking off until FR-19 shows a measured benefit; this fixes what counts before the data exists |
| P10-7 | Metrics (FR-19 P1) | Precision@K (denominator K) and nDCG@K (gain 2^grade − 1, discount log2(rank + 1), ideal from the labeled items), K ∈ {1, 3, 5}, exactly as `q13-v1` defines them, with hand-computed tests. The report gives one row per configuration and per technology, with paired differences, their intervals and denominators, and labels the results indicative. | Already approved as policy, so the policy ID stays `q13-v1`, and the P0 fingerprint is unchanged |
| P10-8 | Full benchmark (DS-06) | **50 questions: the 30 smoke questions plus 20 new ones.** The 20 are 16 answerable, 4 per technology, with at least one identifier lookup and one how-to each. The other 4 are unanswerable but in the domain, such as a feature the frozen pages do not cover; the smoke negatives are all other technologies. That gives 14 of 50 unanswerable (28%, against at least 15%). Claude Code drafts them from the corpus with stable anchors and graded relevance, paraphrasing rather than copying the anchor passage. A second person reviews them, and disagreements are logged. They are **frozen, hashed and committed before any hybrid or reranker result is computed on them.** Calibration uses smoke only; the new 20 are the check. | Questions written from a passage echo its words, which favours BM25. Paraphrasing reduces that, and the report names the bias. |
| P10-9 | Answer evaluation (FR-19.3) | **20 rated answers, no LLM judge.** Fixed now: the first 20 answerable full-benchmark questions in a seeded order, answered in `hybrid` mode with reranking as configured at that point, by the default Ollama model. Each is rated for faithfulness (claims supported by the cited chunks: yes, partly, no) and answer relevance (answers the question: yes, partly, no), using the Phase 8 tools with a relevance column added. | D-15 prefers manual review first. A judge would add a model, a method and, if hosted, a cost (C-06). Who rates is the owner's decision. |
| P10-10 | Provider demo (C-07, AC-22.4) | **A full switch: OpenAI chat and embeddings in a second configuration file**, run with the same `ask` command as under Ollama. It includes the index rebuild that C-07 requires, the vector calibration on that profile, an invalid-key run (AC-16.3) and the costs.<br>**DDIA is kept out by construction:** the OpenAI profile has its own `data_directory`, holding a copy of the registry with DDIA deleted. A fail-closed guard also refuses to embed or prompt any version outside the public manifest under a non-local provider, and a test covers it.<br>Code gaps: an OpenAI embedding branch with its profile identity, token budgeting for a tokenizer other than the verified byte-level BPE, and the profile file.<br>Model IDs and prices are looked up at the gate, not assumed. The owner creates the key, sets it only in the environment, and sets a spend cap. | Rebuilding 816 public chunks and running one smoke benchmark costs little. Alternative: switch chat only and keep Ollama embeddings, which C-03 allows as a local model. That needs no rebuild, but it splits `provider` into chat and embedding providers and does not exercise the rebuild. |
| P10-11 | Dependencies (VULN-08, P9-11) | Every new package (reranker runtime, `langchain-openai` and what it pulls in) passes the Phase 9 gate and is pinned with hashes. **Convert the whole lock to hashes first**, as the P9-11 chore, so it is not done twice. | P9-11 put this after Phase 9. Doing it later means rehashing again after the new packages. |
| P10-12 | Deferred items | P9-6 secondary categories stay deferred: this phase adds no documents without a user category. Entity and keyphrase boosting stay out of scope (P9-10). | Nothing in Phase 10 can measure them |

## Pre-registration

As in Phase 9's round 2, these are fixed before the data they judge exists:

- The fusion parameters are the requirement defaults. Any sweep of `k`, depth or weights is a diagnostic only, never a selection.
- The hybrid gate's candidates and selection rule (P10-3), the measured-benefit rule (P10-6) and the answer sample (P10-9) are fixed in this plan.
- The 20 new questions are committed before any hybrid or reranker run touches them. Every proposal comes from smoke, and the full run is made once per configuration for the report.

## Work sequence

Steps 1 to 3 need no download, key or spend, so they run first. Owner-blocked work comes last and is isolated. Each step ends with its offline tests passing, and new test modules go into `GROUPS` in `scripts/run_tests.py`.

| Step | Work | Output and check |
|---|---|---|
| 0 | Approve or amend P10-1 to P10-12 | Recorded in [decisions](DECISIONS.md) as Phase 10 contracts |
| 1 | Metrics and runner: Precision@K and nDCG@K, the four-configuration runner, per-technology tables, paired bootstrap | AC-19.3; P0 fingerprint unchanged |
| 2 | Hybrid: candidate-depth refactor, `rrf-v1`, the degraded path, component relevances, `hybrid` in `search` and `ask` | AC-14.1 to AC-14.4; invariant 1 |
| 3 | Reranker interface with a mocked reranker; the gate and degraded path; the call log | AC-15.1 to AC-15.4 |
| 4 | Full benchmark: draft the 20 new questions, review, freeze and commit (can run beside steps 1 to 3) | `datasets/benchmark_full.jsonl`, review log |
| 5 | P9-11 hashed lock, then the reranker dependency gate and the real reranker | Gate record; model pinned and hashed |
| 6 | Runs: smoke in four configurations for the proposals, owner adopts thresholds; the full benchmark once per configuration; `eval --refusal` in the new modes | AC-15.5, AC-19.2, FR-18 for new modes |
| 7 | Answer evaluation: 20 answers rated | FR-19.3 |
| 8 | Provider demo: OpenAI gate, embedding branch, guard, public-only rebuild, calibration, the same `ask` under both, an invalid key, costs | AC-22.4, C-07, C-06 |
| 9 | Phase 10 report, traceability, README and roadmap; the full offline suite in groups | `docs/PHASE_10_STATUS.md` |

## Your time

| Task | Estimate |
|---|---|
| Approve or amend P10-1 to P10-12 | 30 minutes |
| Review the 20 new questions | 30 to 45 minutes |
| Rate 20 answers for faithfulness and relevance (unless designated) | 45 to 60 minutes |
| Create an OpenAI key, set a spend cap, set `OPENAI_API_KEY` | 10 minutes |
| Adopt the threshold proposals and decide any default change | 15 minutes |

## Risks

- **Small samples.** 50 questions give noisy differences. The report gives paired intervals and labels everything indicative.
- **Benchmark bias.** Questions drafted from passages favour lexical match. Paraphrasing and the in-domain negatives reduce this; the report states it.
- **Reranker cost on this machine.** CPU latency and memory with Ollama loaded may rule out larger models. The gate measures both before anything depends on them.
- **Framework churn.** `langchain-community` warns that it is being sunset. The reranker avoids depending on it if a direct path passes the gate.
- **Private data.** DDIA is 70% of the index. The OpenAI profile excludes it by construction and by a tested guard.
- **New score scales.** Each new mode gets its own scale ID and thresholds; none reuses another mode's thresholds silently (Q-07).

## Out of scope

Entity or keyphrase boosting, an LLM reranker, an LLM judge, the web UI (P2), and the NFR performance gates, which Phase 11 measures. Phase 10 records latency but does not judge NFR-02.
