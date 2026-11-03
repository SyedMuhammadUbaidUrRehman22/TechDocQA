# Smoke benchmark review log

Benchmark: [benchmark_smoke.jsonl](benchmark_smoke.jsonl), 30 questions, 20 answerable and 10 unanswerable. Corpus: the frozen public reference `techdocqa-reference-2026-10-24-v2` (20 documents). The private DDIA supplement is excluded from every run and carries no labels.

## Status

**Not reviewed.** All 30 questions are marked `"review": "draft"`. Claude Code drafted them on 2026-11-03 at the project owner's request, from the stored chunk text of the public reference. FR-19 requires that the team writes the benchmark and a second person reviews it, with disagreements resolved and logged here. Neither step has happened. Every run report counts the draft questions and labels its metrics provisional until they are reviewed.

## How labels work

Each answerable question lists one or more relevant items. An item is a `source_key` from the frozen manifest plus either a verbatim `anchor` from the document or a `section` heading path, with a `grade`:

- `2`: the passage answers the question.
- `1`: the passage supports the answer, or answers part of it.
- `0`: labeled not relevant; it never counts as a hit.

Anchors are matched case-insensitively with whitespace collapsed, against the current chunks of the active version, on every run. They name text, not chunk IDs, so they survive re-chunking. If a source is deleted, withdrawn or leaves the evaluation scope, or an anchor stops matching, the run flags the question and excludes it from the metrics. The file is not edited (AC-21.3).

On 2026-11-03 every anchor resolved to at least one current chunk.

## What the reviewer checks

For each answerable question:

1. The question is answerable from the labeled passages alone.
2. No other passage in the public reference answers it as well and is missing from the labels. A missing passage makes the metrics look worse than retrieval really is.
3. Each grade is right.
4. The wording does not copy the anchor so closely that BM25 is favored.

For each unanswerable question, nothing in the 20 public documents answers it. Then change `draft` to `reviewed` for each accepted question. The edit changes the dataset hash, which is intended.

## Points for the reviewer

| Question | Point |
|---|---|
| smoke-ood-03 | The Airflow tasks page says a worker "failed its liveness probe" under Kubernetes. It does not explain how to configure one, so the question was kept as unanswerable. It is the hardest negative for BM25. |
| smoke-kafka-01 | There are two items: the batching behavior and the default value. They are in neighboring chunks, so finding only one gives recall 0.5. |
| smoke-kafka-03, smoke-airflow-05 | A grade 1 item counts as relevant for Recall and MRR in P0. Graded gain only matters for P1 nDCG. |
| smoke-spark-05 | The answer is split across two documents, the cluster overview glossary and the `--deploy-mode` option list. Both are labeled. |
| smoke-spark-03 | The anchor keeps the source Markdown emphasis (`**4-8 disks**`, `_without_`), because chunk text is not stripped of markup. |
| All | The questions were written after reading the passages. Wording close to the source favors BM25 and makes the set easier than real user questions. |

## Disagreements

None recorded, because no review has taken place.

| Date | Question | Reviewer's position | Resolution |
|---|---|---|---|
