# Phase 6 smoke benchmark and retrieval metrics

Implementation and evidence checkpoint 2026-11-03 on Windows, Python 3.13.3, local Ollama 0.40.13. Phase 6 adds the FR-19 smoke runner, Recall@1/3/5 and MRR for BM25 and vector search, the `eval` command and benchmark flags for deleted sources. Answering, refusal calibration, hybrid search and P1 metrics remain later phases.

**Result:** the runner meets AC-19.1, AC-19.3, AC-19.4, AC-19.5 and AC-21.3 on the real corpus and in tests. **The benchmark itself is not reviewed.** Claude Code drafted all 30 questions at the project owner's request. FR-19 requires the team to write them and a second person to review them. Until both happen, every metric below is provisional and FR-19 P0 is not complete. See [Open items](#open-items).

## What was added

| Area | Behavior | Code |
|---|---|---|
| Dataset | JSONL questions with a `type`, a `review` status and graded labels. Each label is a manifest `source_key` plus a verbatim `anchor` or a `section` path, never a chunk ID. The loader rejects a question with no relevant item unless it is marked `unanswerable`, and an unanswerable one with relevant items. Its ID is the file name; its hash covers the exact bytes. | [dataset.py](../src/techdocqa/evaluation/dataset.py) |
| Metrics | Recall@K and MRR over labeled items, each counted once, macro-averaged. MRR is cut at rank 5. | [metrics.py](../src/techdocqa/evaluation/metrics.py) |
| Runner | Resolves labels against current chunks, then runs each question through the same `search()` the CLI uses. The scope is limited to the manifest's evaluation documents. A failed mode is reported and the other mode still runs. | [runner.py](../src/techdocqa/evaluation/runner.py) |
| Search scope | `search()` takes an optional set of source keys. It limits the corpus itself, so BM25 statistics come only from the public reference. CLI search is unchanged. | [search.py](../src/techdocqa/retrieval/search.py) |
| Deletion flags | `Registry.deleted_document_ids()` reads the anonymous `DOCUMENT_DELETED` events. The runner maps them to labels through the manifest's document IDs. | [registry.py](../src/techdocqa/registry.py) |
| CLI | `eval [--dataset] [--manifest] [--mode bm25\|vector ...] [--report-dir]` prints a JSON summary and writes a JSON and a Markdown report. Exit 0 if every mode completed, 1 otherwise. | [cli.py](../src/techdocqa/cli.py) |
| Benchmark | 20 answerable questions, five per technology, and 10 out-of-domain unanswerable ones. All three question types are present. | [benchmark_smoke.jsonl](../datasets/benchmark_smoke.jsonl), [review_log.md](../datasets/review_log.md) |

The label, metric and exclusion rules are recorded in [decisions](DECISIONS.md#phase-6-contracts-2026-11-03).

## Measured results

Committed report: [eval_81b33ca0e87744eabe3e2bd630477657](../reports/evaluation/eval_81b33ca0e87744eabe3e2bd630477657.md) ([JSON](../reports/evaluation/eval_81b33ca0e87744eabe3e2bd630477657.json)). Machine: 12.6 GB RAM, NVIDIA MX450 with 2 GB VRAM.

| Configuration | Evaluated | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|---|---|---|---|
| BM25 | 20 | 0.475 | 0.825 | 0.925 | 0.708 |
| Vector | 20 | 0.575 | 0.825 | 0.925 | 0.783 |

With 20 answerable questions, one question moves a mean by up to 0.05. The differences above are a few questions each and are indicative only.

| Check | Actual result |
|---|---|
| AC-19.1 time | Both modes: **40.1 s** and **35.1 s** in two runs, limit 300 s. BM25 alone takes about 2.6 s. No model was downloaded. |
| AC-19.4 repeat | Two runs: **identical results fingerprint** `9992d76f...6fb787` and identical metrics, with different run IDs. |
| Identity | Dataset sha256 `ee4b24a7...de01cda`, corpus fingerprint `e8713f0c...a2c4b5`, BM25 config `rc_53aa7ebc...`, vector config `rc_5b4d2678...`, code `a93afd3` plus the uncommitted Phase 6 working tree, which the report records as `dirty: true`. |
| Scope | 20 of 20 manifest documents searchable, **816 chunks**. The private DDIA supplement was excluded from every search. No content drift from the frozen manifest. |
| Anchors | All 26 labeled items resolved to at least one current chunk. No flags. |
| First relevant item | Within the top 5 for **all 20** answerable questions in both modes. |
| Recall misses | All from two-item questions: the grade 1 item of `smoke-kafka-03` and `smoke-airflow-05`, and the second document of `smoke-spark-05`. Each costs 0.5 of one question in both modes. |
| Unanswerable | Both modes return results for all 10, as expected before FR-18 refusal. |
| Top-1 score spread | Vector: answerable 0.879 to 0.939, unanswerable 0.798 to 0.837, so the ranges do not overlap on this set. BM25: answerable 16.3 to 57.0, unanswerable 10.5 to 22.4, so they overlap. Input for Phase 8 calibration, not a refusal result. |
| Complete offline suite | **349 passed, 2 skipped, 0 failed**, one existing warning, 576 s. The skips are the opt-in live smoke tests. 21 tests are new. |

### Vector query time

The first vector-only trial took 115 s for 30 queries, about 3 s each after a 20 s cold start. Stage timing in a separate process showed where the time goes: Ollama's model list, which `build_embeddings` calls on every query to check the pinned digest, took **2.6 to 3.0 s**. The embedding took 0.17 s and the Chroma search 0.03 s. In the two later full runs, vector queries took a median of 0.98 s, so the list call's cost varies. This explains part of the Phase 5 NFR-02 miss. The check was not cached, because caching would stop it from detecting a model swapped during a long run. Phase 11 remains the formal latency measurement.

## Reproduce

From the repository root in PowerShell, with Ollama running:

```powershell
.\.venv\Scripts\techdocqa.exe eval --report-dir reports\evaluation
.\.venv\Scripts\techdocqa.exe eval --mode bm25
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation.py --basetemp=.tmp/phase6
```

Without `--report-dir`, reports go to the ignored `data\evaluation`. Two runs on unchanged inputs must print the same `results_fingerprint`.

## Acceptance boundaries

| Requirement | Status |
|---|---|
| AC-19.1 | Met on the real corpus, 35 to 40 s. |
| AC-19.3 | Met: hand-computed tests, including the source's MRR 0.5 example. |
| AC-19.4 | Met on the real corpus and in tests. |
| AC-19.5 | Met in tests. |
| FR-19 P0 overall | **Not complete.** The benchmark is not team-written and not second-person reviewed. Q-12 and Q-13 are implemented as proposed but not formally approved. |
| FR-19.4 and 19.5 records | Run ID, dataset ID and hash, corpus fingerprint, configuration IDs, provider and model with digest, library versions, code commit and dirty flag, dates and per-question results. Per-technology breakdowns are included, though they are P1. |
| AC-21.3 | Met in tests: after a deletion, the next run flags the question as `SOURCE_DELETED`, excludes it and leaves the benchmark file byte-identical. Withdrawn, out-of-scope and unresolved labels are flagged too. **Not run against the real registry**, to avoid deleting a corpus document. |
| FR-22 | `eval` added for the smoke slice. `ask` is still missing, so AC-22.1 and AC-22.3 stay incomplete. |
| DS-06, NFR-05, NFR-06 | 30 questions, versioned and hashed in the repository. Each run records versions and configuration. Repeated runs give identical retrieval results. |

## Open items

- **Second-person review.** Use [review_log.md](../datasets/review_log.md). Accepting a question means changing `draft` to `reviewed`, which changes the dataset hash. Then rerun `eval` and commit the new report. Phase 8 calibration should use the reviewed set.
- **Q-12 and Q-13 approval.** An approval or amendment changes the metric policy ID.
- **Question bias.** The questions were written after reading their passages, and some wording is close to the source, which favors BM25. Unanswerable questions are all clearly out of domain, as AC-18 asks. Only `smoke-ood-03` shares terms with the corpus.
- **AC-12.1 and NFR-02 from Phase 5 remain open.** Phase 6 measures retrieval on questions, not sentence queries, so it does not close AC-12.1.

## Limits

- **Metrics are item-based.** A long passage split over two chunks counts once. Retrieving the second half still counts if it holds the anchor.
- **A flagged question is excluded as a whole**, even if only one of its labels is invalid. The report lists each exclusion.
- **Anchors are exact text.** A normalization or extraction change that alters an anchor's text flags the question as `ANCHOR_UNRESOLVED` rather than silently counting a miss.
- **Evaluation runs are not in the registry's `runs` table.** The report file is the run record.
