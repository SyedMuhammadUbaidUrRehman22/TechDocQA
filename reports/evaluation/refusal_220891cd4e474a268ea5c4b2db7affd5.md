# Refusal check refusal_220891cd4e474a268ea5c4b2db7affd5

- Date: 2026-11-04T15:21:17.362669+00:00, 415.587 s
- Model: `ollama/qwen3:1.7b@8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`, generation config `gc_a370881aa0ee`, warm-up loaded in 3929 ms
- Retrieval: bm25, config `rc_c1c2e21c571b`, relevance policy `bm25-query-max-v1`
- Thresholds: min_top_score 0.297285, min_chunk_score 0.297285, min_supporting_chunks 1, calibration run `eval_c4ab1f1397fa469489137f611b74cdf7`
- Dataset: `benchmark_smoke` sha256 `11710120d0f8bd83f5988d78813cb979511bb7aba808b679c884db3ccfb92faa`; corpus fingerprint `e8713f0c15eeb6db2c801a319c2324507302242c6265b8fff1ae67db63a2c4b5`
- Code: e06e2753c93acb59f948309179a21a226a0bb534 (dirty: True)

| Check | Result |
|---|---|
| AC-18.1 unanswerable refused (`no_evidence`) | 10 of 10 = 1.0, target 0.9 (met) |
| AC-18.2 answerable answered | 19 of 20 = 0.95, target 0.85 (met) |
| Refused by the gate / chat requests among them | 10 / 0 |
| Chat requests in the run | 20 of 30 questions |
| Statuses | answered 19, no_evidence 11, generation_error 0 |
| Unanswerable outcomes | LOW_RELEVANCE 10 |
| Answerable outcomes | INSUFFICIENT_CONTEXT 1, answered 19 |
| Retrieval ms, median / p95 / max | 116.5 / 225 / 4546 |
| Generation ms, median / p95 / max | 14126.0 / 30923 / 31002 |
| Total ms, median / p95 / max | 14671.0 / 31655 / 31735 |

## Questions

| Question | Unanswerable | Status | Reason | Top relevance | Gate passed | Chat request | Citations | Total ms |
|---|---|---|---|---|---|---|---|---|
| smoke-kafka-01 | no | answered |  | 0.392488 | True | yes | 2 | 22395 |
| smoke-kafka-02 | no | answered |  | 0.494331 | True | yes | 1 | 26565 |
| smoke-kafka-03 | no | answered |  | 0.386613 | True | yes | 1 | 21392 |
| smoke-kafka-04 | no | answered |  | 0.43615 | True | yes | 1 | 19296 |
| smoke-kafka-05 | no | answered |  | 0.380923 | True | yes | 2 | 25110 |
| smoke-airflow-01 | no | answered |  | 0.537892 | True | yes | 1 | 20968 |
| smoke-airflow-02 | no | answered |  | 0.340187 | True | yes | 1 | 31655 |
| smoke-airflow-03 | no | no_evidence | INSUFFICIENT_CONTEXT | 0.347682 | True | yes | 0 | 26960 |
| smoke-airflow-04 | no | answered |  | 0.429471 | True | yes | 1 | 17040 |
| smoke-airflow-05 | no | answered |  | 0.407505 | True | yes | 1 | 13223 |
| smoke-spark-01 | no | answered |  | 0.41121 | True | yes | 1 | 24158 |
| smoke-spark-02 | no | answered |  | 0.363289 | True | yes | 1 | 21136 |
| smoke-spark-03 | no | answered |  | 0.407819 | True | yes | 1 | 12192 |
| smoke-spark-04 | no | answered |  | 0.567608 | True | yes | 1 | 11425 |
| smoke-spark-05 | no | answered |  | 0.435086 | True | yes | 4 | 31735 |
| smoke-postgresql-01 | no | answered |  | 0.59416 | True | yes | 1 | 9619 |
| smoke-postgresql-02 | no | answered |  | 0.490617 | True | yes | 2 | 15802 |
| smoke-postgresql-03 | no | answered |  | 0.467812 | True | yes | 1 | 22555 |
| smoke-postgresql-04 | no | answered |  | 0.425729 | True | yes | 1 | 13540 |
| smoke-postgresql-05 | no | answered |  | 0.327768 | True | yes | 1 | 21100 |
| smoke-ood-01 | yes | no_evidence | LOW_RELEVANCE | 0.142761 | False | no | 0 | 38 |
| smoke-ood-02 | yes | no_evidence | LOW_RELEVANCE | 0.173442 | False | no | 0 | 210 |
| smoke-ood-03 | yes | no_evidence | LOW_RELEVANCE | 0.266802 | False | no | 0 | 50 |
| smoke-ood-04 | yes | no_evidence | LOW_RELEVANCE | 0.145397 | False | no | 0 | 460 |
| smoke-ood-05 | yes | no_evidence | LOW_RELEVANCE | 0.209774 | False | no | 0 | 54 |
| smoke-ood-06 | yes | no_evidence | LOW_RELEVANCE | 0.149341 | False | no | 0 | 39 |
| smoke-ood-07 | yes | no_evidence | LOW_RELEVANCE | 0.189884 | False | no | 0 | 49 |
| smoke-ood-08 | yes | no_evidence | LOW_RELEVANCE | 0.138147 | False | no | 0 | 38 |
| smoke-ood-09 | yes | no_evidence | LOW_RELEVANCE | 0.152782 | False | no | 0 | 47 |
| smoke-ood-10 | yes | no_evidence | LOW_RELEVANCE | 0.115524 | False | no | 0 | 28 |
