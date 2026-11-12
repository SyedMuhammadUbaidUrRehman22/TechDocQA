# Smoke benchmark run eval_bfa563bc8aa544e29cb839fb7f26c1b1

- Date: 2026-11-12T14:33:15.492441+00:00, 93.337 s (limit 300 s: met)
- Dataset: `benchmark_smoke` sha256 `11710120d0f8bd83f5988d78813cb979511bb7aba808b679c884db3ccfb92faa`, 30 questions (20 answerable, 10 unanswerable, 0 draft)
- Corpus: `techdocqa-reference-2026-10-24-v2`, 20 of 20 documents, 816 chunks, fingerprint `e8713f0c15eeb6db2c801a319c2324507302242c6265b8fff1ae67db63a2c4b5`
- Code: 95dd5213112027829bc56077737e1dfb83517cc7 (dirty: True), metric policy `q13-v1`
- Results fingerprint: `48ce89dc9571f45ce3db455dc97cbaef474301fb9e49f4054cb719d21a3af410`

| Configuration | Config ID | Evaluated | Excluded | recall@1 | recall@3 | recall@5 | mrr |
|---|---|---|---|---|---|---|---|
| bm25 | `rc_c1c2e21c571b` | 20 | 0 | 0.475 | 0.825 | 0.925 | 0.708 |
| vector | `rc_240565250e0c` | 20 | 0 | 0.575 | 0.825 | 0.925 | 0.783 |

## By technology

| Configuration | Technology | Questions | recall@1 | recall@3 | recall@5 | mrr |
|---|---|---|---|---|---|---|
| bm25 | Apache Airflow | 5 | 0.500 | 0.700 | 0.900 | 0.750 |
| bm25 | Apache Kafka | 5 | 0.400 | 0.800 | 0.900 | 0.633 |
| bm25 | Apache Spark | 5 | 0.400 | 0.800 | 0.900 | 0.650 |
| bm25 | PostgreSQL | 5 | 0.600 | 1.000 | 1.000 | 0.800 |
| vector | Apache Airflow | 5 | 0.500 | 0.900 | 0.900 | 0.733 |
| vector | Apache Kafka | 5 | 0.500 | 0.900 | 0.900 | 0.800 |
| vector | Apache Spark | 5 | 0.700 | 0.700 | 0.900 | 0.850 |
| vector | PostgreSQL | 5 | 0.600 | 0.800 | 1.000 | 0.750 |

## Top-1 scores

Raw scores in each mode's own scale. FR-18 calibration uses the 0-1 relevance below.

| Configuration | Answerable min / median / max | Unanswerable min / median / max | Unanswerable with results |
|---|---|---|---|
| bm25 | 16.251407 / 28.760587 / 57.030823 | 10.495169 / 14.230894 / 22.409484 | 10 of 10 |
| vector | 0.879468 / 0.902022 / 0.938665 | 0.798434 / 0.82051 / 0.836978 | 10 of 10 |

## Refusal calibration (FR-18)

Top-1 relevance on each mode's 0-1 scale, judged before context trimming. A proposal takes effect only when its section below is copied into the configuration, which makes this run the calibration run.

| Configuration | Answerable min / median / max | Unanswerable min / median / max | Proposed threshold | Margin | Answerable passed | Unanswerable refused | Leave-one-out errors | Active thresholds |
|---|---|---|---|---|---|---|---|---|
| bm25 | 0.327768 / 0.41847 / 0.59416 | 0.115524 / 0.151062 / 0.266802 | 0.297285 | 0.030483 | 20 of 20 | 10 of 10 | 0 | 0.297285 from `eval_c4ab1f1397fa469489137f611b74cdf7`: 20 of 20 passed, 10 of 10 refused |
| vector | 0.879468 / 0.902022 / 0.938665 | 0.798434 / 0.82051 / 0.836978 | 0.858223 | 0.021245 | 20 of 20 | 10 of 10 | 0 | 0.858223 from `eval_c4ab1f1397fa469489137f611b74cdf7`: 20 of 20 passed, 10 of 10 refused |

```toml
[retrieval.sufficiency.bm25]
min_top_score = 0.297285
min_chunk_score = 0.297285
min_supporting_chunks = 1
calibration_run_id = "eval_bfa563bc8aa544e29cb839fb7f26c1b1"
scoring_config_id = "sc_be0c0c0942c7f01a9f79ec75effb0366f2cd39d5ec70ee4e71ba64b4a3f43507"
```

```toml
[retrieval.sufficiency.vector]
min_top_score = 0.858223
min_chunk_score = 0.858223
min_supporting_chunks = 1
calibration_run_id = "eval_bfa563bc8aa544e29cb839fb7f26c1b1"
scoring_config_id = "sc_c40598d9e99ee950f32c22d25aff430b6602a18316cb48f50ee5996048005cb2"
```

## Flags

None.

## Notes

- Indicative only: 20 answerable and 10 unanswerable questions; one question moves a mean by 0.050.
- The same questions calibrate FR-18 refusal, so calibration and this assessment overlap; this is not an independent holdout.
- Results are cut at rank 5: MRR scores 0 when the first relevant item is below that rank.
- 1 searchable document(s) outside the evaluation manifest were excluded from every search.
