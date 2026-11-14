# Latency profile latency_2fef1c3ae3ad460da6b28c8e104476aa (retrieval)

- Date: 2026-11-14T04:52:18.291284+00:00, 145.159 s; procedure `p11-latency-v1` (P11-1)
- Code: 09666f2ce0733af0ca21b74c1a84084b98c3401a (dirty: False)
- Hardware: 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz, 4 cores / 8 threads, 11.8 GB RAM, GPUs: Intel(R) Iris(R) Xe Graphics, NVIDIA GeForce MX450; test processes running: 0
- Runtime at start: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU); 8 logical CPUs, RAM 3.1 of 11.8 GB free; on AC power
- Runtime at end: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU); 8 logical CPUs, RAM 3.0 of 11.8 GB free; on AC power
- Scope: whole (the whole local index); 50 questions of `benchmark_full`, 3 passes after one warm-up per configuration

| Configuration | Searches | Median (s) | p95 (s) | Max (s) | Target (s) | NFR-02 | Degraded | Changed rankings |
|---|---|---|---|---|---|---|---|---|
| bm25 | 150 | 0.033 | 0.041 | 0.071 | 1.0 | met | 0 | 0 |
| vector | 150 | 0.098 | 0.129 | 0.265 | 1.0 | met | 0 | 0 |
| hybrid | 150 | 0.117 | 0.134 | 0.154 | 1.0 | met | 0 | 0 |
| hybrid+rerank | 150 | 0.677 | 0.841 | 0.954 | 5.0 | met | 0 | 0 |

## Stages: bm25

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.018 | 0.018 | 0.024 | 0.535 |
| bm25_search | - | 1.0 | 0.015 | 0.016 | 0.019 | 0.45 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.003 |
| unattributed | - | - | 0.000 | 0.000 | 0.001 | 0.012 |

## Stages: vector

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.018 | 0.017 | 0.022 | 0.173 |
| embedding_profile | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| vector_store_open | - | 1.0 | 0.005 | 0.004 | 0.005 | 0.046 |
| vector_store_empty_check | - | 1.0 | 0.001 | 0.001 | 0.002 | 0.011 |
| query_embedding | - | 1.0 | 0.063 | 0.059 | 0.089 | 0.614 |
| vector_search | - | 1.0 | 0.016 | 0.015 | 0.019 | 0.151 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.001 |
| unattributed | - | - | 0.001 | 0.001 | 0.001 | 0.005 |

## Stages: hybrid

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.018 | 0.017 | 0.023 | 0.153 |
| embedding_profile | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| bm25_search | - | 1.0 | 0.017 | 0.016 | 0.021 | 0.14 |
| bm25_rescore | - | 0.26 | 0.002 | 0.000 | 0.009 | 0.018 |
| vector_store_open | - | 1.0 | 0.004 | 0.004 | 0.005 | 0.038 |
| vector_store_empty_check | - | 1.0 | 0.001 | 0.001 | 0.001 | 0.008 |
| query_embedding | - | 1.0 | 0.059 | 0.059 | 0.061 | 0.495 |
| vector_search | - | 1.0 | 0.015 | 0.015 | 0.019 | 0.128 |
| stored_relevances | - | 1.0 | 0.002 | 0.000 | 0.009 | 0.013 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.001 |
| unattributed | - | - | 0.001 | 0.001 | 0.001 | 0.005 |

## Stages: hybrid+rerank

| Stage | Inside | Calls per search | Mean (s) | Median (s) | p95 (s) | Share of mean |
|---|---|---|---|---|---|---|
| registry_read | - | 1.0 | 0.027 | 0.026 | 0.038 | 0.04 |
| embedding_profile | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| bm25_search | - | 1.0 | 0.022 | 0.022 | 0.031 | 0.032 |
| bm25_rescore | - | 1.0 | 0.010 | 0.010 | 0.016 | 0.015 |
| vector_store_open | - | 1.0 | 0.006 | 0.006 | 0.008 | 0.009 |
| vector_store_empty_check | - | 1.0 | 0.001 | 0.001 | 0.002 | 0.002 |
| query_embedding | - | 1.0 | 0.099 | 0.092 | 0.145 | 0.146 |
| vector_search | - | 1.0 | 0.014 | 0.014 | 0.019 | 0.021 |
| stored_relevances | - | 1.0 | 0.011 | 0.011 | 0.016 | 0.016 |
| rerank | - | 1.0 | 0.486 | 0.480 | 0.635 | 0.717 |
| config_id | - | 1.0 | 0.000 | 0.000 | 0.000 | 0.0 |
| unattributed | - | - | 0.001 | 0.001 | 0.001 | 0.001 |
