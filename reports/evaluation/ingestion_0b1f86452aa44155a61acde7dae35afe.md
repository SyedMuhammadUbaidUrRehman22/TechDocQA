# Ingestion timing ingestion_0b1f86452aa44155a61acde7dae35afe (reference)

- Date: 2026-11-14T05:04:50.035039+00:00; code 74e2ab9cb17983ff860d327467fb1f1f6fa5e920 (dirty: False)
- Runtime at start: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU); 8 logical CPUs, RAM 5.3 of 11.8 GB free; on AC power
- Runtime at end: Python 3.13.3; Ollama 0.40.16 (nomic-embed-text:latest 100% GPU); 8 logical CPUs, RAM 5.3 of 11.8 GB free; on AC power
- 20 documents (13 html, 3 md, 3 pdf, 1 txt), 1,513,828 bytes; 816 chunks, 808 distinct texts
- Embedding: 808 texts in 35 requests from an empty cache (cache miss proved: True)
- Content hashes equal to the manifest: 20 of 20; failures {'process': 0, 'chunk': 0, 'index': 0, 'enrich': 0}

| Stage | Seconds |
|---|---|
| ingest | 1.7 |
| process | 35.6 |
| chunk | 19.0 |
| index | 152.1 |
| enrich | 7.8 |
| **To searchable (ingest to index)** | **208.5** |
| With enrich | 216.296 |

NFR-04 (at most 30 min with local embeddings): **met**.
