# Phase 8 calibrated refusal and P0 release gate

Implementation and evidence checkpoint 2026-11-04 on Windows, Python 3.13.3, local Ollama 0.40.13 with `qwen3:1.7b` and `nomic-embed-text:latest`. Phase 8 adds the FR-18 sufficiency gate: each retrieval mode has its own 0-1 relevance scale and its own thresholds, calibrated on the reviewed smoke benchmark. When the chunks kept for the prompt are not relevant enough, `ask` refuses without calling the model. Phase 8 also adds a real-model refusal check, a real-model CLI smoke script, and a reconciliation of every P0 acceptance criterion.

**Result:** FR-18 is met. On all 30 smoke questions with the real model, each mode refused 10 of 10 out-of-domain questions and answered 19 of 20 answerable ones, against targets of 90% and 85%. No gate refusal made a model call. AC-18.3 to AC-18.5 and AC-21.1 are met in tests, and AC-21.1 and AC-22.3 are also met through the CLI script with the real models. **The P0 release gate passed on 2026-11-07.** At this checkpoint, AC-16.6 and AC-12.1 were open and Q-07, Q-12 and Q-13 were unapproved. All were settled in the [gate update of 2026-11-07](#gate-update-2026-11-07). See [P0 reconciliation](#p0-acceptance-reconciliation).

## What was added

| Area | Behavior | Code |
|---|---|---|
| Score scales (Q-07) | Every search result has a `relevance` from 0 to 1 next to its raw score. Vector relevance is the FR-12 score, `(cosine + 1) / 2`. BM25 relevance divides the raw score by the most that query could score, with words absent from the corpus counted at the IDF of an unseen term. The BM25 ranking does not change. | [lexical.py](../src/techdocqa/retrieval/lexical.py), [search.py](../src/techdocqa/retrieval/search.py) |
| Thresholds | `[retrieval.sufficiency.bm25]` and `[retrieval.sufficiency.vector]` hold `min_top_score`, `min_chunk_score`, `min_supporting_chunks`, the calibration run ID and a `scoring_config_id`. Thresholds apply only while that ID matches the active score scale, so a new embedding model or BM25 setting makes them stale rather than silently reused. | [settings.py](../src/techdocqa/settings.py), [sufficiency.py](../src/techdocqa/answering/sufficiency.py), [default.toml](../config/default.toml) |
| Gate | After retrieval and context trimming, before the chat model is built. The best kept chunk must meet `min_top_score`, and enough kept chunks must meet `min_chunk_score`. A failure is `no_evidence` / `LOW_RELEVANCE` with fixed wording and no model call. Nothing retrieved stays `NO_MATCHING_DOCUMENTS`, and provider failures stay `generation_error`. | [generation.py](../src/techdocqa/answering/generation.py) |
| Visibility (AC-18.5) | `retrieval_config_id` now includes the thresholds that apply and their calibration run, so `search` and `ask` report the same ID. Each answer carries `sufficiency` (thresholds, run ID, top relevance, supporting chunks, verdict) and `llm_called`. `config-check` reports each mode as `calibrated`, `stale` or `not_calibrated`. `ask --text` explains a refusal and warns when no threshold applies. | [schemas.py](../src/techdocqa/schemas.py), [cli.py](../src/techdocqa/cli.py) |
| Calibration | Every `eval` report has a Refusal calibration section. Per mode, it proposes the midpoint between neighboring top scores with the best balanced accuracy, reports leave-one-out errors and shows the configuration section to adopt. It also judges the run with the active thresholds. | [runner.py](../src/techdocqa/evaluation/runner.py), [sufficiency.py](../src/techdocqa/answering/sufficiency.py) |
| Refusal check | `eval --refusal [--mode M]` asks every smoke question with the real model, in the evaluation scope, and reports AC-18.1, AC-18.2 and the chat requests made by gate refusals. | [answers.py](../src/techdocqa/evaluation/answers.py) |
| Warm-up | `eval --answers`, `eval --refusal` and the live injection test load the chat model before timing, with Ollama's empty-prompt request and the same context window. | [generation.py](../src/techdocqa/answering/generation.py) |
| CLI smoke (AC-22.3) | `scripts\cli_smoke.ps1` runs ingest, process, chunk, index, search, ask, withdraw, ask and status with the real models, in a temporary data directory that it deletes afterwards. | [cli_smoke.ps1](../scripts/cli_smoke.ps1) |

The rules are recorded in [decisions](DECISIONS.md#phase-8-contracts-2026-11-04).

### Why BM25 needed its own scale

Raw BM25 scores grow with the length of the question and the rarity of its words, so they cannot share one threshold. In the Phase 6 run, the weakest answerable question scored 16.25 and the strongest out-of-domain question 22.41. Dividing by the best score the query could reach gives a share of what was possible. Counting absent words matters most: "How do I import an existing resource into Terraform state?" matches some common words, but the corpus has no `terraform`, so the best it can reach is a small share.

| Top-1 BM25 value | Weakest answerable | Strongest unanswerable | Separated |
|---|---|---|---|
| Raw score | 16.25 | 22.41 | No |
| Raw over the ceiling, absent words ignored | 0.340 | 0.408 | No |
| Raw over the ceiling, absent words at the unseen IDF (adopted) | **0.328** | **0.267** | **Yes** |

The raw row is from the Phase 6 report, the middle row from a one-off analysis on the evaluation scope, and the adopted row from every `eval` report. On all 21 documents, which is what `ask` searches, the same one-off analysis gave 0.347 against 0.283, so the adopted threshold also separates there.

## Calibration

Calibration run [eval_c4ab1f1397fa469489137f611b74cdf7](../reports/evaluation/eval_c4ab1f1397fa469489137f611b74cdf7.md): the reviewed 30-question smoke set (sha256 `11710120...ccfb92faa`), the 20-document public reference, DDIA excluded. Its retrieval metrics equal Phase 6: BM25 Recall@5 0.925, MRR 0.708; vector Recall@5 0.925, MRR 0.783.

| Mode | Answerable top-1 relevance, min / median / max | Unanswerable, min / median / max | Adopted threshold | Margin | Leave-one-out errors |
|---|---|---|---|---|---|
| BM25 | 0.328 / 0.418 / 0.594 | 0.116 / 0.151 / 0.267 | **0.297285** | 0.030 | 0 of 30 |
| Vector | 0.879 / 0.902 / 0.939 | 0.798 / 0.821 / 0.837 | **0.858223** | 0.021 | 0 of 30 |

In both modes every answerable question scores above every unanswerable one, so each threshold sits in the middle of the gap. `min_chunk_score` equals `min_top_score` and one supporting chunk is required. The same 30 questions are used to assess refusal, so this is not a holdout result.

Two later runs with the thresholds active, [eval_066786323f5143ebbc6801923198c25d](../reports/evaluation/eval_066786323f5143ebbc6801923198c25d.md) and a second one kept outside the repository, gave identical `results_fingerprint` values (`f034eb7a...e260b5`) and the same metrics. At retrieval level they pass 20 of 20 answerable and refuse 10 of 10 unanswerable questions in each mode. The fingerprint differs from Phase 6 because configuration IDs now include the thresholds and the reports now include relevance values.

## Measured results

### Refusal with the real model (AC-18.1, AC-18.2)

`eval --refusal` asked every smoke question through `ask`'s own code, scoped to the evaluation manifest, after loading the chat model.

| Mode | AC-18.1: unanswerable refused | AC-18.2: answerable answered | Gate refusals / their chat requests | Chat requests | Total time per question, median / p95 | Run |
|---|---|---|---|---|---|---|
| Vector | **10 of 10** (target 90%) | **19 of 20 = 0.95** (target 85%) | 10 / **0** | 20 of 30 | 14.0 s / 27.4 s | [refusal_c8929f41](../reports/evaluation/refusal_c8929f41dc324c868df0af405a43a24b.md) |
| BM25 | **10 of 10** (target 90%) | **19 of 20 = 0.95** (target 85%) | 10 / **0** | 20 of 30 | 14.7 s / 31.7 s | [refusal_220891cd](../reports/evaluation/refusal_220891cd4e474a268ea5c4b2db7affd5.md) |

Every out-of-domain question was refused by the gate with no model call, in 2.0 to 3.6 s in vector mode, which embeds the question, and in 28 to 460 ms in BM25 mode. Each mode missed one answerable question, and they missed different ones. In vector mode smoke-spark-05 passed the gate at 0.894, and in BM25 mode smoke-airflow-03 passed at 0.348; in both cases the model replied `INSUFFICIENT_CONTEXT`, and the other mode answered the same question. So the misses come from the model's reading of the chunks it was given, not from the gate.

The ten out-of-domain questions are all clearly outside the corpus, as AC-18.1's example is. Questions close to the corpus but unanswered by it, such as an unlisted Kafka setting, have not been tested.

### CLI smoke script (AC-22.3, AC-21.1)

`scripts\cli_smoke.ps1` passed all 9 checks with the real models, using only `techdocqa` commands. It wrote two small documents of its own to a temporary directory and never touched the project registry.

| Step | Result |
|---|---|
| ingest, process, chunk, index | 2 documents, each run `completed` with 0 failed |
| search | The Halcyon guide ranked first of 3 results |
| ask | `answered`, citing the Halcyon guide, relevance 0.944 against 0.858 |
| withdraw | `withdrawn` |
| ask again | `no_evidence` / `LOW_RELEVANCE`, best remaining relevance 0.718, **no model call** |
| status | `withdrawn` |

### Prompt injection rerun (AC-23.3)

`pytest --live-model -m live_model` passed on its first attempt this time, after a 2.3 s warm-up. All 3 questions about the fixture's fictional `zephyr.queue.depth` setting were answered with `[C1]` and the setting stated correctly, and no raw or final output contained "PWNED". Prompts were 366 to 378 tokens. The test turns the gate off, because it checks the model and BM25 relevance on its one-document corpus is not calibrated.

### Cold start

With no model loaded, one `ask` took 43.8 s in total: 20.1 s of retrieval, which included loading the embedding model, and 23.4 s of generation, which included loading the chat model. Generation has a 60 s deadline, so this fits. Warm, the same question took 19.2 s, because only one of the two models fits in the 2 GB of VRAM and they swap on every question. The warm-up before each refusal check took 11.2 s. Phase 7's 61.1 s timeout was not reproduced; the warm-up keeps a cold load from counting against the first answer of a timed run.

## Tests

| Suite | Result |
|---|---|
| New offline tests | 23: 22 in `test_sufficiency.py` and 1 in `test_indexing.py`, for the AC-05.1 and AC-05.4 counts. |
| Complete offline suite | **428 passed, 3 skipped, 0 failed**, one existing warning. The skips are the two `--live` network tests and the `--live-model` test. |
| Suite time | 1,797 s, against 510 to 576 s in earlier phases. One test, `test_reprocessing_does_not_reactivate_withdrawn_content`, took 674 s of it; alone it takes 4.1 s, and the stall did not recur. Real-model commands ran during the suite, which slowed it, but they do not clearly explain a stall of that length. |
| Live model test | See the injection rerun above. |

The scripted chat model records every prompt, so each "no model call" is checked by its call count. Tests cover a hand-computed BM25 relevance; worked calibration examples, including ties, empty retrieval and a leave-one-out count of 3; thresholds that load from TOML and fail validation; another mode's or a changed scale's thresholds never applying; a refusal just above the top score and an answer exactly at it; the post-trimming recheck; empty index and empty filter results; provider failures with good retrieval; a withdrawn answer source; the eval proposal pasted back as configuration; and the refusal run and its CLI.

## P0 acceptance reconciliation

Every P0 acceptance criterion, with where its evidence is. "Tests" means the offline suite; "real" means the real corpus or the configured models.

| FR | Criterion | Status | Evidence |
|---|---|---|---|
| FR-01 | AC-01.1 to AC-01.5 | Met | Tests ([Phase 2](PHASE_2_STATUS.md)). All 21 corpus documents registered. |
| FR-02 | AC-02.1, AC-02.2, AC-02.4 | Met | Tests ([Phase 2](PHASE_2_STATUS.md), [Phase 3B](PHASE_3B_STATUS.md)). |
| FR-02 | AC-02.3, AC-02.5 | Met | Real: every entry matches the registry and every chunk resolves ([Phase 5](PHASE_5_STATUS.md)). |
| FR-03 | AC-03.1 to AC-03.5 | Met | Tests with fixtures ([Phase 3B](PHASE_3B_STATUS.md)). |
| FR-04 | AC-04.1 to AC-04.4 | Met | Tests ([Phase 3B](PHASE_3B_STATUS.md), review corrections). |
| FR-05 | AC-05.1 to AC-05.5 | Met | Tests for the document layer ([Phase 3B](PHASE_3B_STATUS.md)). The chunk and index counts in AC-05.1 and AC-05.4 gained a test in this phase. |
| FR-06 P0 | AC-06.1 to AC-06.3 | Met | Tests ([Phase 4](PHASE_4_STATUS.md)). AC-06.4 is P1. |
| FR-10 | AC-10.1 to AC-10.7 | Met | Tests and real: 816 public-reference chunks against about 3,000 ([Phase 4](PHASE_4_STATUS.md)); the re-chunked index part of AC-10.5 in Phase 5 tests. |
| FR-11 | AC-11.1 to AC-11.3, AC-11.5 | Met | Real and tests ([Phase 5](PHASE_5_STATUS.md)). |
| FR-11 | AC-11.4 | Met in tests only | A fake second embedder; no real second model was run. |
| FR-12 | AC-12.1 | Met as amended | Index recall@3 against exact search **1.0** on 143 sentence queries, target 0.99 ([gate update](#gate-update-2026-11-07)). As written, 112 of 143. |
| FR-12 | AC-12.2 to AC-12.7 | Met | Real and tests ([Phase 5](PHASE_5_STATUS.md)). |
| FR-13 | AC-13.1 to AC-13.5 | Met | Real and tests ([Phase 5](PHASE_5_STATUS.md)). |
| FR-16 | AC-16.1 | Met | Real 10 of 10 ([Phase 7](PHASE_7_STATUS.md)); 19 of 20 in the vector refusal check. |
| FR-16 | AC-16.2 to AC-16.5 | Met | Tests; AC-16.3 also on the real adapter ([Phase 7](PHASE_7_STATUS.md)). |
| FR-16 | AC-16.6 | Met, AI reviewer | 8 of 10 rated yes, 1 partly, 1 no, in the [answer report](../reports/evaluation/answers_d724f334f9f0409884db95613c61663e.md). The reviewer is Claude, designated by the owner; the criterion as written asks for a human reviewer. |
| FR-17 | AC-17.1 to AC-17.4 | Met | Tests ([Phase 7](PHASE_7_STATUS.md)). |
| FR-18 | AC-18.1, AC-18.2 | Met | Real: see [Refusal](#refusal-with-the-real-model-ac-181-ac-182). |
| FR-18 | AC-18.3, AC-18.4, AC-18.5 | Met | Tests in this phase; AC-18.5 also in [default.toml](../config/default.toml), every report and `config-check`. |
| FR-19 smoke | AC-19.1, AC-19.3 to AC-19.5 | Met | Real and tests ([Phase 6](PHASE_6_STATUS.md)); calibrated runs in this phase took 57 to 63 s. AC-19.2 is P1. |
| FR-20 | AC-20.1 to AC-20.4 | Met | Tests; AC-20.4 also real ([Phase 5](PHASE_5_STATUS.md)). |
| FR-21 | AC-21.1 | Met | Tests and the real-model CLI script. |
| FR-21 | AC-21.2, AC-21.3 | Met in tests only | Not run on the real registry, to avoid deleting corpus documents ([Phase 5](PHASE_5_STATUS.md), [Phase 6](PHASE_6_STATUS.md)). |
| FR-22 | AC-22.1, AC-22.2 | Met | Tests ([Phase 7](PHASE_7_STATUS.md), [Phase 2](PHASE_2_STATUS.md)). |
| FR-22 | AC-22.3 | Met | Real-model CLI script in this phase; offline workflow test since Phase 7. |
| FR-22 | AC-22.4 | P0 part met in tests | The same `ask` runs with `provider = "openai"` in configuration against a stand-in OpenAI module. A demonstration with both real providers is P1 (Phase 10). |
| FR-23 | AC-23.1, AC-23.2, AC-23.4 | Met | Tests ([Phase 2](PHASE_2_STATUS.md), [Phase 7](PHASE_7_STATUS.md)). |
| FR-23 | AC-23.3 | Met | Real model, as a mitigation check; see the rerun above. AC-23.5 is P2. |

**P0 release decision: passed on 2026-11-07.** The owner confirmed the 2026-11-04 amendments to AC-12.1 and AC-16.6 and approved Q-07, Q-12 and Q-13 ([approvals](DECISIONS.md#p0-approvals-2026-11-07)). Two limits remain on record: AC-16.6 was rated by an AI reviewer, not the human reviewer its text names, and the criteria marked "in tests only" were not run on the real registry. The NFRs, including NFR-02's vector-search latency (p95 1.377 s against 1 s in Phase 5), are measured formally in Phase 11.

## Gate update (2026-11-07)

Both changes are recorded in [decisions](DECISIONS.md#p0-gate-amendments-2026-11-04).

**AC-16.6.** `eval --record-review` copied the ratings into the [answer report](../reports/evaluation/answers_d724f334f9f0409884db95613c61663e.md): 8 of 10 yes, 1 partly (`smoke-airflow-03`, an unsupported "sequentially") and 1 no (`smoke-kafka-03`, an unsupported and wrong claim about when a consumer sees a message). The reviewer is Claude Opus 5.5, designated by the project owner. The source text asks for a human reviewer.

**AC-12.1.** `datasets/verify_index.py --live` on the real corpus, 7 min 52 s, result `passed`:

| Measure | Value |
|---|---|
| Sentence queries (every third public chunk with a whole sentence outside its overlap) | 143 |
| **Index recall@3 against exact search** (amended criterion, target 0.99) | **1.0** |
| Index top 3 equal to exact top 3 | 143 of 143 |
| Exact hits lost by the index | 0 |
| Sentence finds its chunk in the top 3: index / exact / exact on public documents only | 112 / 112 / 122 |
| Sentence finds its chunk in the top 3: BM25 | 143 |
| Identifier queries at rank 1 | 8 of 8 |

The sample is 143 rather than Phase 5's 152 because the corrected sampler no longer ends a sentence at a dotted name. As written, AC-12.1 would be 112 of 143 (78.3%). BM25 found every sentence's chunk, which supports the P1 hybrid plan. Warm vector search in this run had p95 3.564 s and max 21.762 s, against 1.377 s in Phase 5, with BM25 at 0.157 s. The run followed a long stall in which Ollama stopped answering, so this timing is not a clean measurement; NFR-02 is measured in Phase 11.

**Approvals.** On 2026-11-07 the owner confirmed both amendments and approved Q-07, Q-12 and Q-13. The metric policy ID became `q13-v1`; the Q-07 IDs and thresholds are unchanged. The first evaluation under the approved policy, [`eval_50d06f55b10541ccbccc0ef6d77abb9d`](../reports/evaluation/eval_50d06f55b10541ccbccc0ef6d77abb9d.md) (40.8 s), repeated the calibration run's metrics in both modes: BM25 Recall@5 0.925 and MRR 0.708, vector Recall@5 0.925 and MRR 0.783. Its active thresholds answered 20 of 20 and refused 10 of 10 in each mode, and no label was flagged. Its results fingerprint `48ce89dc...a3af410` differs from the calibration run's only through the policy ID.

## Open items

- **Optional human rating for AC-16.6.** A person can fill in `data/evaluation/answers_d724f334f9f0409884db95613c61663e_review.md` and run `eval --record-review`, which replaces the recorded ratings.
- **Recalibration.** The thresholds belong to this corpus, models and BM25 settings. A new embedding model or BM25 setting makes them stale, which `ask` and `config-check` report. Corpus changes do not, so rerun `eval` after material corpus changes.

## Limits

- **The calibration questions are the assessment questions.** With 20 and 10 questions, rates move by 5 and 10 points per question. Leave-one-out found no errors, but the vector margin is 0.021.
- **The unanswerable questions are far from the corpus.** A question on a covered technology that the documents do not answer would score closer to the threshold; none was tested.
- **`ask` searches every eligible document**, including the private DDIA supplement, while calibration and the refusal check use the 20-document public reference. Asked through plain `ask` over all 21 documents, the 10 out-of-domain questions were still all refused in both modes with no model call, but closer to the thresholds: the strongest scored 0.846 against 0.858 in vector mode and 0.283 against 0.297 in BM25. Answerable questions were not rerun over all 21 documents.
- **Only the top chunk decides in practice.** With one supporting chunk required, `min_chunk_score` adds nothing; the smoke set is too small to calibrate it separately.
- **Generation is not deterministic**, so AC-18.2 can vary between runs by the model's own `INSUFFICIENT_CONTEXT` replies. Retrieval and the gate are deterministic.
- **The gate cannot judge support.** It measures relevance. A relevant chunk can still lack the answer, which the model's insufficiency reply or the human review must catch.

## Reproduce

From the repository root in PowerShell, with Ollama running:

```powershell
.\.venv\Scripts\techdocqa.exe config-check
.\.venv\Scripts\techdocqa.exe eval --report-dir reports\evaluation
.\.venv\Scripts\techdocqa.exe eval --refusal --mode vector --report-dir reports\evaluation
.\.venv\Scripts\techdocqa.exe eval --refusal --mode bm25 --report-dir reports\evaluation
powershell -ExecutionPolicy Bypass -File scripts\cli_smoke.ps1
.\.venv\Scripts\python.exe -m pytest tests\test_sufficiency.py --basetemp=.tmp/phase8
.\.venv\Scripts\python.exe -m pytest tests\test_generation.py --live-model -m live_model -s --basetemp=.tmp/phase8live
```
