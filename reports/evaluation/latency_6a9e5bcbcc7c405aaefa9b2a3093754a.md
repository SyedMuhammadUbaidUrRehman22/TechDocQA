# Latency profile latency_6a9e5bcbcc7c405aaefa9b2a3093754a (retrieval)

- Date: 2026-11-14T04:27:35.945970+00:00, 185.093 s; procedure `p11-latency-v1` (P11-1)
- Code: c6d6e2fd7893561939cf914cf9b204db15574959 (dirty: False)
- Hardware: 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz, 4 cores / 8 threads, 11.8 GB RAM, GPUs: Intel(R) Iris(R) Xe Graphics, NVIDIA GeForce MX450; test processes running: 0
- Runtime at start: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU); 8 logical CPUs, RAM 1.8 of 11.8 GB free; on AC power
- Runtime at end: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU); 8 logical CPUs, RAM 1.5 of 11.8 GB free; on AC power
- Scope: evaluation (20 sources); 50 questions of `benchmark_full`, 3 passes after one warm-up per configuration

| Configuration | Searches | Median (s) | p95 (s) | Max (s) | Target (s) | NFR-02 | Degraded | Changed rankings |
|---|---|---|---|---|---|---|---|---|
| bm25 | 150 | 0.027 | 0.044 | 0.082 | 1.0 | met | 0 | 0 |
| vector | 150 | 0.117 | 0.148 | 0.309 | 1.0 | met | 0 | 0 |
| hybrid | 150 | 0.117 | 0.145 | 0.154 | 1.0 | met | 0 | 0 |
| hybrid+rerank | 150 | 0.917 | 1.090 | 1.399 | 5.0 | met | 0 | 0 |

## Stages: bm25

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.024 | 0.021 | 0.037 | 0.806 |
| bm25_search | - | 1.0 | 0.005 | 0.005 | 0.009 | 0.178 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.003 |
| unattributed | - | - | 0.000 | 0.000 | 0.001 | 0.013 |

## Stages: vector

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.033 | 0.032 | 0.051 | 0.274 |
| embedding_profile | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| vector_store_open | - | 1.0 | 0.007 | 0.006 | 0.011 | 0.056 |
| vector_store_empty_check | - | 1.0 | 0.001 | 0.001 | 0.002 | 0.01 |
| query_embedding | - | 1.0 | 0.068 | 0.064 | 0.077 | 0.562 |
| vector_search | - | 1.0 | 0.011 | 0.010 | 0.017 | 0.091 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.001 |
| unattributed | - | - | 0.001 | 0.001 | 0.001 | 0.006 |

## Stages: hybrid

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.030 | 0.029 | 0.043 | 0.25 |
| embedding_profile | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| bm25_search | - | 1.0 | 0.006 | 0.005 | 0.010 | 0.051 |
| bm25_rescore | - | 0.2 | 0.001 | 0.000 | 0.004 | 0.006 |
| vector_store_open | - | 1.0 | 0.006 | 0.006 | 0.010 | 0.052 |
| vector_store_empty_check | - | 1.0 | 0.001 | 0.001 | 0.002 | 0.01 |
| query_embedding | - | 1.0 | 0.062 | 0.063 | 0.067 | 0.528 |
| vector_search | - | 1.0 | 0.010 | 0.010 | 0.016 | 0.088 |
| stored_relevances | - | 1.0 | 0.001 | 0.000 | 0.004 | 0.005 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.002 |
| unattributed | - | - | 0.001 | 0.001 | 0.001 | 0.008 |

## Stages: hybrid+rerank

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.038 | 0.038 | 0.052 | 0.041 |
| embedding_profile | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| bm25_search | - | 1.0 | 0.008 | 0.007 | 0.013 | 0.008 |
| bm25_rescore | - | 1.0 | 0.005 | 0.004 | 0.009 | 0.005 |
| vector_store_open | - | 1.0 | 0.007 | 0.007 | 0.011 | 0.008 |
| vector_store_empty_check | - | 1.0 | 0.001 | 0.001 | 0.002 | 0.002 |
| query_embedding | - | 1.0 | 0.114 | 0.101 | 0.183 | 0.123 |
| vector_search | - | 1.0 | 0.013 | 0.013 | 0.018 | 0.014 |
| stored_relevances | - | 1.0 | 0.007 | 0.007 | 0.010 | 0.008 |
| rerank | - | 1.0 | 0.727 | 0.734 | 0.880 | 0.788 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| unattributed | - | - | 0.002 | 0.002 | 0.002 | 0.002 |
