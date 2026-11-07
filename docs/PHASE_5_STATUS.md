# Phase 5 lexical and vector search, and document lifecycle

Implementation and evidence checkpoint 2026-11-02 on Windows, Python 3.13.3, local Ollama 0.40.13. Phase 5 adds embeddings, a persisted vector index, BM25 search, withdrawal and deletion. Hybrid search, reranking, answering and evaluation remain later phases.

**Result:** the index is complete, reproducible and correctly gated by the registry on the real corpus. **Two measurements miss their targets and stay open:** AC-12.1 on the real corpus (124 of 152 sentence queries, 81.6%) and the NFR-02 retrieval target for vector search (warm p95 1.377 s against 1 s). See [Open results](#open-results).

The chunk artifacts and the frozen manifest are unchanged. The corpus remains 20 public documents (816 chunks) plus the private DDIA supplement (1,919 chunks), 2,735 in total. DDIA stays excluded from the public reference, and its text is not committed or sent off the machine.

## What was added

| Area | Behavior | Code |
|---|---|---|
| Embeddings | One validated vector per `chunk_key`: expected dimension, finite values, nonzero norm and unit length under the `l2` profile. An invalid vector is not stored and its chunk is marked `embedding_failed` with a reason. A retry embeds only what failed. | [embeddings.py](../src/techdocqa/indexing/embeddings.py), [pipeline.py](../src/techdocqa/indexing/pipeline.py) |
| Model pinning | Before any embedding call, the installed model's digest is compared with the configured one. A changed model returns `EMBEDDING_MODEL_CHANGED` rather than mixing vectors. | [embeddings.py](../src/techdocqa/indexing/embeddings.py) |
| Vector store | Chroma through LangChain, persisted under `data/index/chroma`, one collection per embedding profile, cosine distance, telemetry off. Relevance is `1 - distance / 2`, which equals `(cosine + 1) / 2`. It is a 0-1 scale, not a probability. | [vector_store.py](../src/techdocqa/indexing/vector_store.py) |
| BM25 | LangChain `BM25Retriever` with `k1` and `b` from settings. It needs no provider. It scores all eligible chunks and then filters, so a filter changes neither a chunk's score nor the candidates available. | [lexical.py](../src/techdocqa/retrieval/lexical.py) |
| Search | One filter contract for both modes: `document_id`, `technology`, `category` (exact, case-insensitive) and `entity`. Ties break on `chunk_id`. `hybrid` and `rerank` return `MODE_NOT_AVAILABLE`. | [search.py](../src/techdocqa/retrieval/search.py) |
| Lifecycle | `withdraw` and `delete`, with a required reason. Re-ingesting withdrawn content reactivates it. | [lifecycle.py](../src/techdocqa/indexing/lifecycle.py) |
| Registry | Schema version 2 adds `embedding_profiles`, `embeddings`, `chunk_embeddings` and `verified_entities`. Version 1 registries upgrade in place when opened. Downgrade is unsupported. | [registry.py](../src/techdocqa/registry.py) |

### BM25 tokenization rule

Text is case-folded. Each whole technical form is one token: `snake_case`, `camelCase`, `dotted.names`, `HTTP/2`, `C++`, `C#`, `--flag-name`. Its plain word parts follow it, so `max.poll.interval.ms` also yields `max`, `poll`, `interval` and `ms`, and `maxMemoryPolicy` also yields `max`, `memory` and `policy`. There are no stop words and no stemming, so `transaction` does not match `transactions`. A result must share at least one token with the query, because BM25 IDF can reach zero in a small corpus.

### What each search can see

| Version state | BM25 | Vector |
|---|---|---|
| Active with chunks, not yet indexed | Yes | No, until `index` runs |
| Active and indexed | Yes | Yes |
| Re-chunked or reactivated | Yes | No, until `index` runs |
| Superseded, withdrawn, or a duplicate of another source | No | No |

Vector search restricts Chroma to the eligible version IDs and rechecks each result's version and chunking configuration, so stale entries cannot be returned or crowd out live ones. Withdrawal and supersession take effect when their registry transaction commits. The next `index` run then removes the entries physically.

## Measured results

Index contents were produced by `run_08baf27982654ff19b7ae1c8f22e55e6` after a nine-chunk trial on one document. Machine: 12.6 GB RAM, NVIDIA MX450 with 2 GB VRAM. Timings are single observations, not the NFR measurement planned for Phase 11.

| Check | Actual result |
|---|---|
| Corpus indexing run | 21 versions, 0 failed, 94 provider requests, **548 seconds** total process time. 2,718 chunks embedded in this run, plus the 9 from the trial. |
| Index contents | **2,735 entries, 2,727 stored vectors**; 8 occurrences share a vector with identical text. No `embedding_failed` rows. Entries equal the eligible chunks exactly. |
| AC-11.3, AC-20.4 repeat run | Provider deliberately unreachable: **0 model calls, 21 skipped, 0 failed**, 15.2 s, entry count unchanged. |
| AC-11.5 stability | Same text embedded three times: minimum cosine **1.0**. |
| AC-02.3, AC-02.5 | Every entry's metadata equals the registry projection and every chunk resolves to its version and document. SQLite integrity `ok`, 0 foreign-key errors. |
| AC-12.6 restart | Separate process: **identical top-5 and scores** for 10 queries in both modes. |
| AC-12.7 rebuild | `data/index/chroma` deleted, then `index --rebuild` with the provider unreachable: 2,735 entries restored, **0 model calls**, 28.2 s, **identical top-5 and scores**. |
| AC-13.1 identifiers | **8 of 8** at rank 1, each present in the rank 1 chunk: `linger.ms`, `enable.idempotence`, `spark.memory.fraction`, `spark.local.dir`, `pg_subtrans`, `wal_writer_delay`, `idle_in_transaction_session_timeout`, `execution_timeout`. The requirement's example `max.poll.interval.ms` is not in this corpus; a fixture covers it. |
| AC-13.3 | Provider unreachable: BM25 returns results. Vector search returns retryable `EMBEDDING_PROVIDER_UNAVAILABLE`, exit 1. |
| AC-12.1 on the real corpus | **124 of 152** (see below). The offline fixture passes. |
| Warm query time, in process, 50 queries | BM25 median 0.075 s, p95 **0.138 s**. Vector median 0.889 s, p95 **1.377 s**, maximum 1.915 s. |
| One-shot CLI search, including startup | 3.6 to 5.3 s in either mode, four observations. |
| Disk | Vector index 30 MB; registry with vectors 14.5 MB. |
| Complete offline suite | **328 passed, 2 skipped, 0 failed**, one existing warning, 510 s. The skips are the existing opt-in live smoke tests. |
| Corpus verifier | 21 documents, 2,735 chunks, 816 public-reference chunks, passed. |
| Dependencies | `pip check`: no broken requirements. Lock regenerated from a fresh environment, 118 pins. Requirements file hash unchanged, `d458ddb2...d479949`. |

Reproduce from the repository root in PowerShell, with Ollama running:

```powershell
.\.venv\Scripts\techdocqa.exe index
.\.venv\Scripts\python.exe datasets\verify_index.py --snapshot .tmp\top5.json --live
.\.venv\Scripts\python.exe datasets\verify_index.py --compare .tmp\top5.json
Remove-Item -Recurse -Force data\index\chroma
.\.venv\Scripts\techdocqa.exe index --rebuild
.\.venv\Scripts\python.exe datasets\verify_index.py --compare .tmp\top5.json
.\.venv\Scripts\python.exe datasets\verify_corpus.py
.\.venv\Scripts\python.exe -m pytest --basetemp=.tmp/phase5
```

## Open results

**AC-12.1 on the real corpus is not met.** The criterion asks that a query built from a sentence of an indexed chunk returns that chunk in the top 3. Sampling every third public chunk that has a whole sentence outside its overlap:

| Measure | Hits of 152 |
|---|---|
| Chroma index, all 21 documents | **124 (81.6%)** |
| Exact cosine search, all 21 documents | 124 |
| Exact cosine search, public documents only | 133 (87.5%) |

The index is not the cause: it hits the target exactly as often as exact search and returns the same top 3 on 151 of 152 queries. The misses are mostly short, generic sentences with little to identify their source, such as "These possibilities are not covered in this tutorial." In these cases a single-sentence query does not resemble the much longer chunk. DDIA accounts for 9 of the 28 misses by competing for the top 3. Nothing was tuned to raise this figure. An earlier sampler that took the first sentence-like text in a chunk scored 32 of 38, and all 6 of its misses were fragments shared with a neighboring chunk's overlap; it was replaced, and the wider sample above is the result to use. Phase 6 measures retrieval on reviewed questions, and P1 hybrid search is the planned improvement. The criterion should be either met or explicitly amended before P0 release; it is not waived here.

**Update 2026-11-07.** AC-12.1 was amended on 2026-11-04 to index fidelity, recall@3 against exact search, and is met at 1.0 on 143 sentence queries. See [decisions](DECISIONS.md#p0-gate-amendments-2026-11-04) and the [Phase 8 gate update](PHASE_8_STATUS.md#gate-update-2026-11-07).

**NFR-02 is not met for vector search.** The target is p95 at most 1 s without reranking. Warm vector search measured 1.377 s; BM25 measured 0.138 s. Stage timings were not separated, so how much of this is query embedding is not established. A one-shot CLI command takes 3.6 to 5.3 s in total, including process startup, which was not timed separately. Phase 11 remains the formal measurement.

## Acceptance boundaries

| Requirement | Status |
|---|---|
| FR-11 P0 | AC-11.1-11.3 and 11.5 on the real corpus and in tests. AC-11.4 model switch and content change in tests with a fake embedder only; **no real second model was run**. Client retries: `langchain-ollama` exposes no retry setting, so a failed batch is recorded and retried by rerunning `index`. Paid token counts have no provider to measure yet; request counts are logged. |
| FR-12 | AC-12.2-12.7 pass. AC-12.1 passes on the fixture and is open on the real corpus. AC-12.5 uses a synthetic `Redis` fixture because the corpus has no Redis documents. |
| FR-13 | All of AC-13.1-13.5. AC-13.4 `C++` and `HTTP/2` use the fixture. |
| FR-02, FR-20 | AC-02.3, AC-02.5 and AC-20.4 pass. |
| FR-21 | AC-21.2 passes in tests only. **Withdrawal and deletion were not run against the real registry**, to avoid altering its history. AC-21.1 needs QA (Phase 8) and AC-21.3 needs evaluation (Phase 6). |
| FR-22 | `index`, `search`, `withdraw` and `delete` added. `ask` and `eval` remain, so AC-22.1 and AC-22.3 stay incomplete. |
| Entity filter | Registry-backed and tested with seeded rows. No extractor exists until P1, so on the real corpus an entity filter returns no results. |
| OpenAI embeddings | Not implemented; selecting that provider returns `PROVIDER_NOT_AVAILABLE`. |

## Limits

- **`withdraw` keeps vector entries until the next `index` run.** Search cannot return them, but they remain in the Chroma files. `delete` removes them at once.
- **`delete` removes what it can identify.** That covers registry rows, vectors, index entries and snapshots that no other source references, including replaced chunk artifacts. It does not touch your original files in `data/corpus`, or registry backups such as `data/registry.sqlite3.pre-phase5.bak`. Whether Chroma physically overwrites deleted data on disk was not examined.
- **A permanently invalid chunk blocks vector search for its whole document,** visibly as a failed run. BM25 still serves the document.
- **Partial loss of the vector index is repaired by `index` but not detected by search.** Search reports only a completely empty index.
- **Dependencies are heavier.** Chroma brings the environment to 507 MB of packages, including ONNX Runtime and OpenTelemetry that TechDocQA does not call.
- **The BM25 retriever comes from `langchain-community`,** which is being sunset. It is the same pinned package as the Phase 3A loader, and the retriever is a thin use of `rank-bm25`.
- **Ollama is now 0.40.13.** Phase 4 recorded 0.40.10. Model digests are unchanged. The input-limit reasoning from the 0.40.10 source was not rechecked against the newer handler.
