# Latency profile latency_caca243a24f94e829bcd16378b36c4f3 (qa)

- Date: 2026-11-14T04:56:19.960768+00:00, 430.417 s; procedure `p11-latency-v1` (P11-1)
- Code: 09666f2ce0733af0ca21b74c1a84084b98c3401a (dirty: False)
- Hardware: 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz, 4 cores / 8 threads, 11.8 GB RAM, GPUs: Intel(R) Iris(R) Xe Graphics, NVIDIA GeForce MX450; test processes running: 0
- Runtime at start: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU); 8 logical CPUs, RAM 3.2 of 11.8 GB free; on AC power
- Runtime at end: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU, qwen3:1.7b 78%/22% CPU/GPU); 8 logical CPUs, RAM 0.3 of 11.8 GB free; on AC power
- Mode: hybrid, rerank False; warm-up {'loaded': True, 'ms': 7175, 'code': None}
- 36 answerable questions; 35 reached generation, 0 timed out; statuses {'answered': 31, 'no_evidence': 5, 'generation_error': 0}

| Over questions that reached generation | Median (s) | p95 (s) | Max (s) |
|---|---|---|---|
| retrieval | 0.260 | 0.338 | 4.684 |
| generation | 9.874 | 21.710 | 27.561 |
| total | 10.762 | 22.030 | 27.822 |

NFR-03 (p95 at most 60.0 s): **met**. Refused at the gate, no model call, not in the p95: 1 (p95 0.311 s).
