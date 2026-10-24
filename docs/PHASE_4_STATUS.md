# Phase 4 segmentation and framework chunking

Implementation/evidence checkpoint 2026-10-24 on Windows/Python 3.13.3. Before implementation, the reviewed corpus/configuration/documentation checkpoint was committed as **`1ad47d0`**, `chore: freeze reviewed reference corpus and verification evidence`. Phase 4 implements the offline FR-06 P0 sentence-span and FR-10 chunk layer. Embedding generation, vector/BM25 indexes, retrieval and answer generation remain later phases.

The **20-document frozen public reference produces 1,609 chunks**, below the approximate 3,000-chunk target. The separate private DDIA supplement produces **3,934 chunks**. All 21 selected documents therefore produce **5,543 chunks** and would exceed that target if combined into one evaluation corpus. DDIA remains excluded from the public reference because its permissions are unverified. The [source manifest](../datasets/corpus_manifest.json), source hashes and public selection are unchanged.

## Implemented behavior

- `segmentation.py` retains unchanged normalized text and records half-open character spans. Paragraph and sentence punctuation rules protect technical abbreviations, versions, filenames, decimals and known code spans. Concatenating each page's spans reconstructs its normalized text; the existing normalized-page joining contract remains unchanged.
- `chunking.py` uses the already installed and locked **LangChain RecursiveCharacterTextSplitter 1.1.3**. Prose splits at paragraphs, then lines/words/characters. Page and heading boundaries preserve provenance. Fitting protected code blocks remain intact; oversized blocks split at lines, with a character fallback for an oversized single line. Such chunks carry `oversize_split`, while still respecting the hard size/input bound.
- Every chunk records occurrence ID, document/version IDs, index, title, technology, section path, page, original normalized-document index and offsets, exact source substring, size/unit, text hash and chunking config ID. Occurrence IDs include version/config/document-position information so repeated text does not overwrite provenance. Embedding `chunk_key` construction and shared-vector ownership remain Phase 5.
- Tiny chunks merge within their provenance region when the union fits. Otherwise `minimum_exception` records the boundary constraint. Overlap is bounded and reduced where required to preserve fitting code or size limits. The actual 21-document run records **18 minimum-size exceptions, 41 zero-overlap exceptions and 68 chunks marked `oversize_split`**; none exceeds the effective 507-character limit.
- `ingestion/chunks.py` reuses the existing network-disabled processing worker, deadline, snapshot integrity checks, atomic hard-link publication and registry lock/transactions. Immutable JSON artifacts under ignored `data/chunking/artifacts` hold chunks and sentence spans. Existing registry JSON metadata holds the active artifact pointer; **SQLite schema/version 1 is unchanged**.
- `chunk [version_ids ...]` is explicit. Without IDs it selects all active, finalized, nonduplicate registry versions, including an older active version when a newer candidate is still pending. Supply manifest-selected IDs to exclude the rejected Spark navigation page. `active_chunks` rejects inactive/superseded/duplicate sources and verifies artifact/source correspondence before returning text.
- Repeating a verified identical config skips work. Explicit config changes activate the new artifact only after generation and verification succeed. Earlier artifacts remain retained but inactive. Failure, timeout, interrupted work or an activation rollback preserves prior active chunks. CLI `status`, `list`, `history` and run output expose the chunk stage and counts without printing source text.

The parallel review corrected paragraph breaks after abbreviations and explicit code, prevented sentence whitespace from consuming protected indentation, preserved hard-limit-fitting code lines within oversized blocks, and made frozen reference counts portable by source key. Chunking policy is `source-preserving-chunks-v2`; sentence policy is `technical-sentences-v3`. Old-policy sentence spans are verified structurally against immutable source text rather than replayed through a newer algorithm, preserving readable prior artifacts after a failed upgrade. The final corpus was explicitly regenerated under these policies, then repeated unchanged.

## Installed models and input-limit policy

At the user's request, Ollama was installed from the official signed Windows installer; its Authenticode signature was **Valid**. The local service reports **Ollama 0.40.10**. Both selected models were downloaded and their installed metadata recorded under ignored `data/model-profiles`. The model store is outside the repository; no model weights or DDIA content were committed.

| Installed model | Verified metadata | Selected application profile |
|---|---|---|
| `nomic-embed-text:latest` | `nomic-bert`, F16, 137M parameters, 768 embedding dimensions; GGUF context **2048**; model parameters request `num_ctx=8192` | Ollama embeddings; **2048-token input bound** |
| `qwen3:1.7b` | `qwen3`, Q4_K_M; model context **40960**; tokenizer `gpt2` with `qwen2` pretokenization | Ollama chat; configured application context **4096** |

The embedding model digest is `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`. The generation model digest is `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`.

The installed embedding tokenizer is **BERT/WordPiece**, with **30,522 vocabulary entries**, CLS token 101 and SEP token 102. The generation model's tokenizer is different and is not reused for embeddings. Ollama's version-matched [embedding handler](https://raw.githubusercontent.com/ollama/ollama/v0.40.10/server/routes.go) clamps input to the smaller of model metadata and configured `num_ctx`, reserving missing special tokens. Consequently the 8192 parameter does not justify configuring an 8192-token embedding limit for this installed model.

No exact compatible provider token counter is installed. The effective size unit is therefore **characters**, recorded as `python.len` / `unicode-codepoints-v1`; a requested token unit explicitly records its character fallback. This is not a claim of exact BERT tokenization. For the verified WordPiece profile, the implementation uses the conservative bound:

```text
UTF-8 bytes(chunk text) + 17 bytes("search_document: ") + 2 special tokens <= 2048
```

The task prefix follows the [official Nomic model instructions](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5). Reserving four UTF-8 bytes per character caps the requested size 1000 to **507 effective characters**, retaining overlap 150 and minimum 100. The effective config and model digest are part of `chunking_config_id`; every persisted chunk is checked against the input bound. Unsupported/unverified embedding profiles fail before chunk processing. The fallback currently supports only the verified Nomic/BERT profile; other providers/tokenizers require a separate verified implementation. After a model update, reverify metadata/digest and explicitly re-chunk rather than assuming compatibility.

The Unicode-normalization premise of the byte bound was checked across **1,112,064 Unicode scalar values**. That check supports the conservative bound; it does not replace an exact provider tokenizer comparison or an inference test. Model inspection used metadata only: **no generation or embedding inference was run**, including on DDIA.

Observed hardware: **12,639,526,912 bytes RAM**, NVIDIA GeForce MX450 with **2 GB VRAM** and Intel Iris Xe graphics. These are installation facts, not throughput, quality or inference-readiness benchmarks.

## Corpus results

All rows below have status **`chunked`**, `finalized=true`, `is_active=true`. The rejected Spark contents page retains its earlier registry record and was not chunked. The runtime verification projection is `data/phase4-verification.json`; it is not another source catalog or registry.

| Technology | Document | Format | Chunks | Evaluation selection |
|---|---|---|---:|---|
| Apache Airflow | Architecture Overview — Airflow 3.3.2 Documentation | HTML | 49 | Public reference |
| Apache Airflow | Dag Runs — Airflow 3.3.2 Documentation | HTML | 45 | Public reference |
| Apache Airflow | Dags — Airflow 3.3.2 Documentation | HTML | 141 | Public reference |
| Apache Airflow | Tasks — Airflow 3.3.2 Documentation | HTML | 58 | Public reference |
| Apache Kafka | Design \| Apache Kafka | HTML | 239 | Public reference |
| Apache Kafka | Introduction \| Apache Kafka | HTML | 32 | Public reference |
| Apache Kafka | Producer Configs \| Apache Kafka | HTML | 179 | Public reference |
| Apache Kafka | Quick Start \| Apache Kafka | HTML | 39 | Public reference |
| Apache Spark | Cluster Mode Overview | Markdown | 24 | Public reference |
| Apache Spark | Generic Load/Save Functions - Spark 4.0.1 Documentation | HTML | 60 | Public reference |
| Apache Spark | Hardware Provisioning | Markdown | 18 | Public reference |
| Apache Spark | Submitting Applications - Spark 4.0.1 Documentation | HTML | 37 | Public reference |
| Apache Spark | Tuning Spark | Markdown | 80 | Public reference |
| PostgreSQL | PostgreSQL 18 Tutorial: 1. Getting Started | PDF excerpt | 39 | Public reference |
| PostgreSQL | PostgreSQL 18 Tutorial: 2. The SQL Language | PDF excerpt | 76 | Public reference |
| PostgreSQL | PostgreSQL 18 Tutorial: 3. Advanced Features | PDF excerpt | 68 | Public reference |
| PostgreSQL | PostgreSQL: Documentation: 18: 11.2. Index Types | HTML | 29 | Public reference |
| PostgreSQL | PostgreSQL: Documentation: 18: 13.2. Transaction Isolation | HTML | 81 | Public reference |
| PostgreSQL | PostgreSQL: Documentation: 18: 14.1. Using EXPLAIN | HTML | 143 | Public reference |
| PostgreSQL | The PostgreSQL Transaction System | TXT | 172 | Public reference |
| DDIA | Designing Data-Intensive Applications | Markdown | 3,934 | Private supplement, excluded |
| **Public reference** | **20 documents** | **3 MD / 13 HTML / 3 PDF / 1 TXT** | **1,609** | **Within approximate 3,000 target** |
| **All selected** | **21 documents** | **4 MD / 13 HTML / 3 PDF / 1 TXT** | **5,543** | **Combined set exceeds target** |

The common active config ID for this run is `568433628d6e8937a7d22ffc0e7a60297b16f55dd722a1a890e8e65b14ca8314`. PDF chunk pages refer to the local chapter excerpts; original-manual physical-page mappings remain in the frozen manifest. Source license/conversion and HTML-cleaning limitations from the [corpus review](REFERENCE_CORPUS_STATUS.md) still apply.

## Verification

| Check | Actual result |
|---|---|
| First selected-corpus chunk run | `run_4a888b1e164d4388a3bd6e81256079fc`: **21 processed, 0 skipped, 0 failed**, 5,543 chunks, **73.97 seconds**. |
| Identical-config repeat | `run_c7769a0295e84646a40ed04be1108873`: **0 processed, 21 skipped, 0 failed**, unchanged 5,543 chunks, **8.26 seconds**. |
| Actual source coverage | **13,898 sentence spans** reconstruct all **43 normalized Documents/pages**; every chunk resolves to exact source offsets and metadata. |
| Code and overlap checks | **465 fitting code blocks** remain intact; ten sampled same-section overlap pairs match their source substrings. All chunks are nonempty and within the 507-character / conservative 2048-token input bounds. |
| Model metadata | Installed names/digests, embedding context, tokenizer family/vocabulary/special IDs, generation context and independent tokenizer verified. Local API `/api/version` returns **0.40.10**. No inference result is claimed. |
| SQLite checks | Schema version **1**, `integrity_check=ok`, **0 foreign-key errors**. |
| First complete offline Phase 4 suite | **230 passed, 2 skipped**, one existing warning, **97.53 seconds**. |
| Model-selection transition | A later run exposed two CLI tests assuming unselected models: **232 passed, 2 failed, 2 skipped**. The default-profile expectation and explicit unselected-config fixture were corrected. |
| Complete reviewed suite | **243 passed, 2 skipped, 0 failed**, one existing warning, **129.46 seconds**, `.tmp/phase4-reviewed-final.txt`; complete suite before the final protected-indentation guard. |
| Final Phase 4 focused suite | **30 passed, 0 failed**, **92.64 seconds**, `.tmp/phase4-boundary-final.txt`; includes the final indentation guard and all Phase 4 regression cases. |
| Existing configuration check | `config-check --require-models`: exit 0, `configuration_valid`, selection complete; `provider_connection_checked=false` is intentional. |
| Existing corpus verifier | Exit 0: **21 verified documents, 5,543 verified chunks, 1,609 public-reference chunks, 0 duplicate documents**, original source size 2,700,598 bytes. |
| Dependency check | `pip check`: **No broken requirements found.** The already locked splitter is now a direct declaration; no dependency lock change or additional package installation was required for Phase 4. |
| Source preservation | Requirements SHA-256 remains `d458ddb2175d507004806738d3f87de41405d40d39676b52995e07db3d479949`. The frozen corpus manifest and dependency lock are unchanged. |

The two skips are the existing explicitly opt-in Kafka/Airflow live smoke tests. The warning is the existing `langchain-community` sunset notice. New tests exercise technical sentence exceptions, stable spans/config/IDs, ten overlap pairs, fitting/oversized code, repeated-text occurrences, page/heading boundaries, tiny-section exceptions, token fallback, Unicode input bounds, repeat/config switching, corruption, pending/newer and superseded versions, worker failures/timeouts, interrupted-run recovery, activation rollback, CLI stages and sanitized errors. Tests remain offline; corpus verification also uses saved artifacts without a provider.

From the repository root in PowerShell, reproduce the public-reference chunking and checks with the actual CLI:

```powershell
$referenceManifest = Get-Content datasets/corpus_manifest.json -Raw | ConvertFrom-Json
$referenceVersionIds = @($referenceManifest.documents | Where-Object evaluation_included | ForEach-Object version_id)
.\.venv\Scripts\techdocqa.exe chunk @referenceVersionIds
.\.venv\Scripts\techdocqa.exe status --status chunked --json
.\.venv\Scripts\python.exe datasets/verify_corpus.py
.\.venv\Scripts\techdocqa.exe config-check --require-models
.\.venv\Scripts\python.exe -m pytest --basetemp=.tmp/phase4-reviewed-final
.\.venv\Scripts\python.exe -m pip check
```

To re-chunk the private supplement locally, supply its existing version ID, `ver_4b9903f5503c40e1bc66cec52f799a4c`. It remains excluded from public evaluation. Changing size/overlap/unit uses the existing TOML or `--profile` path followed by an explicit `chunk`; merely editing configuration does not rewrite active artifacts.

## Acceptance boundaries and remaining work

FR-06 P0 AC-06.1-06.3 and the FR-10 chunk-layer acceptance are covered by tests and the real-corpus checks above. FR-02 provenance propagation and FR-20's chunk stage are exposed through existing CLI/registry contracts. AC-10.5 is verified for the active chunk artifact; there is **no active vector index yet**, so its index-dependent wording remains Phase 5. FR-06 P1 NLP/F1, embedding quality, vector/BM25 persistence, retrieval/QA, provider throughput and hardware performance remain unimplemented or unmeasured.

The public reference meets the measured chunk target. Including DDIA in a future combined evaluation set requires an explicit dataset/target decision and verified permissions; its 3,934 chunks must not be hidden or counted as part of the current 20-document reference. Exact embedding token counts remain unavailable under the documented conservative character fallback. Retained immutable artifacts have no new garbage-collection mechanism; old-reader downgrades after new JSON metadata are unsupported.

DDIA stayed local. Source documents and model weights remain excluded from Git. No embedding/index/answer pipeline or deployment was performed. At the user's delivery instruction, the preimplementation chore checkpoint `1ad47d0` was pushed first, followed by a separate Phase 4 implementation commit and push.
