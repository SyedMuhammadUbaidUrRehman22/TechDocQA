# Local setup

TechDocQA runs on one machine with a local Ollama server. Everything below is verified on Windows 11 with Python 3.13.3 and Ollama 0.40. Linux, macOS, and Python 3.11 and 3.12 are not verified. The path checks fail closed with `PLATFORM_NOT_SUPPORTED` on a platform they cannot check.

## 1. Install the package

From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\techdocqa.exe config-check
```

`requirements.lock.txt` pins every package, including the test and build tools, together with the SHA-256 of its Windows CPython 3.13 (win_amd64) wheel. pip therefore installs in hash-checking mode and refuses any other file. Another platform or Python version needs its own resolved and hashed lock.

To change a dependency, resolve the new constraints in a fresh environment, run the tests and regenerate the whole lock. Do not edit a single transitive pin by hand.

The lock includes the optional `nlp` extra (spaCy and `rake-nltk`). Neither downloads data: RAKE is given its own stopwords and tokenizer.

## 2. Install Ollama and the pinned models

Install Ollama for your platform. TechDocQA reaches it at `http://127.0.0.1:11434` (`[model] base_url`). Pull the two models:

```powershell
ollama pull qwen3:1.7b
ollama pull nomic-embed-text:latest
ollama list
```

The configuration pins each model by digest, and `ollama list` shows the first 12 characters of it as the ID:

| Model | Role | Pinned digest starts with |
|---|---|---|
| `qwen3:1.7b` | Chat (`ask`) | `8f68893c685c` |
| `nomic-embed-text:latest` | Embeddings (`index`, vector and hybrid search, `enrich`) | `0a109f422b47` |

`:latest` is a tag that moves. A later `ollama pull nomic-embed-text` can install a different model under the same name. TechDocQA then refuses to embed with `EMBEDDING_MODEL_CHANGED` rather than mix vectors from two models in one index. To adopt a new model on purpose:

1. Verify its profile.
2. Update the digest in the configuration.
3. Run `chunk` and then `index`. Each model keeps its own collection.

A changed chat model is refused the same way.

Ollama updates itself, so its version can change between runs. Every evaluation and profiling report records the Ollama version in use and whether each loaded model ran on the CPU or the GPU.

Reranking is optional. It needs the model files once:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_reranker.py
```

This downloads the three pinned files of `cross-encoder/ms-marco-MiniLM-L6-v2` from huggingface.co into `data\models` and checks each file's SHA-256. After that, reranking runs offline on the CPU through `onnxruntime`.

## 3. Check the installation

```powershell
.\.venv\Scripts\techdocqa.exe config-check --require-models
.\.venv\Scripts\python.exe scripts\run_tests.py
powershell -ExecutionPolicy Bypass -File scripts\cli_smoke.ps1
```

- **`config-check --require-models`** checks that a model profile is selected. It does not contact Ollama. The digests are checked against the installed models by the first command that uses each model.
- **`scripts\run_tests.py`** runs the offline suite in four groups, `core`, `retrieval`, `answering` and `enrichment`, one process each, so memory is returned between groups. Name groups to run only those, and pass pytest options after `--`.
  - Do not run the whole suite in one `pytest` process on a machine with little free memory. Chroma keeps every client it creates for the life of the process.
  - The suite blocks outbound sockets and sets `TECHDOCQA_OFFLINE=1`, so it needs no Ollama, models or network.
  - The real reranker test is skipped until `fetch_reranker.py` has run.
  - Tests write scratch data to the ignored `.pytest_tmp`, which pytest replaces on each run.
- **`scripts\cli_smoke.ps1`** runs ingest, process, chunk, index, search, ask, withdraw and ask again with the real models, in a temporary directory that it deletes afterwards.

## 4. Data and the corpus

All runtime data lives in the ignored `data/` directory, the configured `data_directory`:

- the registry, `data/registry.sqlite3`;
- the source snapshots;
- the normalized text and chunks;
- the vector index, `data/index/chroma`;
- logs and evaluation reports.

Keep it private and on a filesystem that supports hard links. Back up the whole directory together, not just the SQLite file.

- `data/index/chroma` can be deleted and restored without any model call by `techdocqa index --rebuild`.
- Registry schema upgrades happen in place on first open, after a verified backup, and older code cannot read the result.

A clean clone has no corpus. To reproduce the frozen public reference, follow [datasets/README.md](../datasets/README.md). It fetches the catalogued pages, registers the local files and checks every hash with `datasets/verify_corpus.py`. The private DDIA supplement is not distributed and cannot be reproduced from the repository. The benchmarks read only the documents that the [frozen manifest](../datasets/corpus_manifest.json) includes for evaluation.

## Network and privacy

TechDocQA uses no hosted model API, and no API key is needed. The OpenAI chat adapter from Phase 7 stays in the code, but its LangChain package is not installed, and the owner withdrew the OpenAI mode.

| What | Contacts | When |
|---|---|---|
| `pip install -r requirements.lock.txt` | PyPI, hash-checked | Setup |
| `ollama pull` | Ollama's model registry | Setup, or on purpose to change a model |
| Ollama's own updater | ollama.com | Whenever the Ollama app checks for updates |
| `scripts\fetch_reranker.py` | huggingface.co, at the pinned revision | Once, if reranking is wanted |
| `ingest --source`, `ingest --url` | The enabled official documentation hosts in `[[online.sources]]`, HTTPS only, within each source's declared scopes | On request only |
| `index`, `search`, `ask`, `eval`, `enrich` | Only Ollama at `127.0.0.1:11434`, when a model is needed | Every run |
| `ingest` of local paths, `process`, `chunk`, BM25 search, `withdraw`, `delete`, `list`, `status`, `history`, `config-check` | Nothing | Never |

- Chroma runs embedded in the process with its anonymized telemetry turned off.
- Set `TECHDOCQA_OFFLINE=1` to stop any fetch outside the tests.
- **LangSmith tracing must stay off.** `langchain-core` installs the LangSmith client, which sends nothing unless one of `LANGSMITH_TRACING_V2`, `LANGCHAIN_TRACING_V2`, `LANGSMITH_TRACING` or `LANGCHAIN_TRACING` is set to `true`. Leave all four unset. If one is set together with an API key, LangChain sends each prompt, which holds the question and the retrieved chunk text, to LangSmith's hosted service.
- Search results print chunk text to the terminal.
- `data\logs\qa.jsonl` stores chunk IDs, configuration IDs, the sufficiency result and timings. The question and the answer appear there only as hashes.
- Evaluation reports hold chunk IDs, never chunk text.
- The tracked reports of runs over the whole index, which includes the private supplement, hold counts and timings only.
- `scripts\scan_secrets.py` checks the tracked files and the whole history for key-shaped strings and for any passage of the private supplement.

Keep credentials out of TOML files, logs and version control. Source URL credentials, query strings and fragments are removed before they are stored.

## Configuration

Settings are in [config/default.toml](../config/default.toml). `--profile config/profiles/ollama.toml` overlays sections of it, and `TECHDOCQA_CHAT_MODEL` and `TECHDOCQA_EMBEDDING_MODEL` override the model names. Relative paths resolve against the base configuration file.

Missing input roots are allowed and never created. A blank path, a root that is not a directory, and a path that escapes the allowed roots through a symlink or junction all fail.

After changing the embedding model, the BM25 settings or the corpus, run `eval`, review the refusal thresholds it proposes, and copy them into `[retrieval.sufficiency.*]`. Until then, `ask` answers in that mode without the gate and warns `SUFFICIENCY_CALIBRATION_STALE`.

Measured hardware needs, timings and the clean-clone check are in the [Phase 11 report](../docs/PHASES.md#phase-11-status). The commands themselves are described in the [command guide](#command-guide) below.

## Command guide

<a id="reference-corpus"></a>
<details>
<summary><strong>Reference corpus</strong></summary>

The [2026-10-24 corpus report](../docs/REFERENCE_CORPUS_STATUS.md) records 20 frozen public/openly licensed documents plus the existing private DDIA supplement: 21 documents, 2,700,598 bytes, five domains, four Markdown, 13 HTML, three text-based PDF excerpts and one TXT. Every selected version is normalized, finalized and active. The public selection meets the format/size/domain requirements without relying on DDIA's unverified permissions. See the [manifest](../datasets/corpus_manifest.json) and [reproduction/verification instructions](../datasets/README.md). Source material stays under ignored `data/`; the manifest contains provenance and hashes only.

</details>

<a id="offline-chunking"></a>
<details>
<summary><strong>Offline chunking</strong></summary>

Use explicit version IDs to chunk the frozen public selection, excluding DDIA and the rejected registry candidate:

```powershell
$referenceManifest = Get-Content datasets/corpus_manifest.json -Raw | ConvertFrom-Json
$referenceVersionIds = @($referenceManifest.documents | Where-Object evaluation_included | ForEach-Object version_id)
.\.venv\Scripts\techdocqa.exe chunk @referenceVersionIds
.\.venv\Scripts\techdocqa.exe status --status chunked --json
.\.venv\Scripts\python.exe datasets/verify_corpus.py
```

The private DDIA version was also chunked locally and remains excluded from public evaluation. `chunk` without IDs processes all active finalized nonduplicate registry versions; review selection is expressed by the version IDs. Repeating the same config verifies and skips existing chunks. To change size/overlap/unit, edit TOML or supply the existing `--profile`, then explicitly run `chunk` again. Previous artifacts stay retained, and only the successful new artifact becomes active. `chunk` prints no source text and sends none to a provider.

</details>

<a id="setup"></a>
<details open>
<summary><strong>Setup</strong></summary>

Use Python 3.11–3.13; Windows Python 3.13.3 is the verified development environment. From this repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe scripts\run_tests.py
.\.venv\Scripts\techdocqa.exe config-check
```

`requirements.lock.txt` pins every package with the SHA-256 of its Windows CPython 3.13 (win_amd64) wheel, so pip installs it in hash-checking mode and refuses any other file. Another platform or Python version needs its own resolved and hashed lock.

`config-check` validates settings without contacting providers. `config-check --require-models` succeeds for the selected default profile; it verifies selection, not connectivity or model quality. TOML settings are in [config/default.toml](../config/default.toml). TECHDOCQA_CHAT_MODEL and TECHDOCQA_EMBEDDING_MODEL override model names. Changing embeddings requires a verified context/tokenizer/digest profile and explicit re-chunking; unsupported profiles fail safely. Relative paths resolve against the base configuration file.

Keep credentials out of TOML, logs and version control. Local runtime data and virtual environments are ignored. Phase 3A uses LangChain's pinned `BSHTMLLoader`, BeautifulSoup, urllib3 and certifi. The archived loader package is a documented maintenance limitation; its network client is never used. The lock also installs spaCy and `rake-nltk`, the optional `nlp` extra used for keyphrases and the spaCy segmentation policy; without them, `enrich` reports keyphrases as unavailable. Reranking needs the model files that `scripts
etch_reranker.py` downloads once (see [Indexing and search](#indexing-and-search)).

The [local setup guide](local_setup.md) covers installing Ollama and the pinned models, checking their digests, the grouped test run, and everything that touches the network.

</details>

<a id="registration-commands"></a>
<details>
<summary><strong>Registration commands</strong></summary>

Put permitted local files under `data/corpus`, or configure other allowed directories. Missing input roots are not created by registration. Blank roots are invalid. Paths outside the configured roots, including symlink/junction escapes, are rejected. The default limits are 20 MiB per file, 500 PDF pages and 60 seconds for PDF structural preflight.

```powershell
.\.venv\Scripts\techdocqa.exe ingest .\data\corpus\kafka.md --technology Kafka --version-label 3.9 --license Apache-2.0 --source-url https://example.org/docs --json
.\.venv\Scripts\techdocqa.exe ingest .\data\corpus --json
.\.venv\Scripts\techdocqa.exe list --json
.\.venv\Scripts\techdocqa.exe status --document-id doc_ID --json
.\.venv\Scripts\techdocqa.exe status --run-id run_ID --json
.\.venv\Scripts\techdocqa.exe status --status registered --json
.\.venv\Scripts\techdocqa.exe history doc_ID --json
```

Use IDs returned by `ingest`; `doc_ID`/`run_ID` illustrate their positions. Each command accepts `--config` and `--profile`, like `config-check`. Output is JSON by default; `--json` also works before the command. `ingest` accepts multiple paths and expands directories one level in sorted order. Every input has an outcome/index; nested/empty directories are explicit failures. A mixed batch preserves its successes and exits 1. Fatal errors are JSON on stderr; invalid CLI syntax exits 2 without echoing argument values. Success/help/version exit 0.

An unchanged source reuses its document/version IDs and increments the run's skipped count. Changed bytes reserve a linked **provisional** registration; `content_hash` stays null, `finalized` and `is_active` stay false until Phase 3 normalization. Equal filenames at different locations require an explicit `--logical-name` to avoid a source-key collision. Identical bytes under different names keep separate document IDs with a provisional `duplicate_of` link. Repeated metadata does not overwrite the original registration snapshot.

The registry is `data/registry.sqlite3` under the configured data directory. After a crashed registration, the next ingestion marks pending orphan attempts `RUN_INTERRUPTED` and safely reuses already committed registrations. Private paths are omitted from CLI records/errors; source URL credentials/query strings/fragments are removed before persistence. Licensing declarations are retained but not independently verified.

</details>

<a id="controlled-online-ingestion"></a>
<details>
<summary><strong>Controlled online ingestion</strong></summary>

The single source catalog is `[[online.sources]]` in [config/default.toml](../config/default.toml). Kafka, Airflow, PostgreSQL and Spark are enabled; Redis and Docker are catalogued but disabled. There is no crawling, sitemap expansion, page-link discovery or JavaScript execution. Kafka's redirect-only entry is retained, while its default page is the explicitly configured official 4.3 introduction.

```powershell
.\.venv\Scripts\techdocqa.exe ingest --source apache_kafka --json
.\.venv\Scripts\techdocqa.exe ingest --source apache_airflow --json
.\.venv\Scripts\techdocqa.exe ingest --source apache_kafka --source apache_airflow --json
.\.venv\Scripts\techdocqa.exe ingest --url https://airflow.apache.org/docs/apache-airflow/stable/ --json
```

Repeat `--source` or `--url` for a finite batch (10 pages by default, configurable up to 20). Choose one selection mode per invocation; online technology/URL identity comes from the catalog, so do not combine online mode with local paths, `--logical-name`, `--technology` or `--source-url`. Existing title/category/version/license/language options still apply. `status`, `list` and `history` expose online provenance through the same registry. Partial batches exit 1 and retain successes.

Only enabled entry points and explicitly listed pages can be requested. Every redirect must remain in that source's declared HTTPS host/path scopes. The fetcher validates all DNS addresses, pins the connection to a public address with original-host TLS/SNI, rejects URL credentials/queries/ambiguous encoded paths and disables automatic redirects, proxies, decompression and library retries. It uses sequential requests, conservative pacing, bounded application retries, connection/read timeouts and an overall fetch/extraction deadline. See [network policy and limitations](../docs/PHASES.md#phase-3a-status-network-and-storage-policy).

Raw HTML and whole-page extracted text live under ignored `data/online`; their byte/text hashes stay distinct. Code spans and heading paths retain structure. `ingest` registrations remain provisional until `process` runs. Repeated identical snapshots reuse IDs and preserve a fresh retrieval attempt; changed bytes create a linked candidate. Processing resolves normalized duplicates and finalizes changed content. The generated `data/online/corpus_manifest.json` is an unfrozen registry projection, not the reference corpus. Usage-policy references remain unverified and do not grant redistribution permission.

To add a source, add one TOML entry with a stable `source_id`, technology/title, HTTPS entry URL, explicit scopes and page list, and usage status/reference; set `enabled=true` after review. Activating an existing disabled source requires only that configuration change. No adapter change is needed. Custom configs must contain their own approved catalog. Keep `data_directory` private and on a filesystem supporting atomic hard-link snapshot publication.

The default suite blocks outbound sockets and sets `TECHDOCQA_OFFLINE=1` for workers. `scripts\run_tests.py` runs it in four groups, one process each, so memory is returned between groups: `core`, `retrieval`, `answering` and `enrichment`. Name groups to run only those, and pass pytest options after `--`. The whole suite takes about 16 minutes. The optional live smoke is explicit:

```powershell
.\.venv\Scripts\python.exe scripts\run_tests.py
.\.venv\Scripts\python.exe scripts\run_tests.py enrichment -- -x
.\.venv\Scripts\python.exe -m pytest tests/test_online.py -m live --live --basetemp=.tmp/phase3a-live
```

Set `TECHDOCQA_OFFLINE=1` yourself to disable worker fetching outside tests. Live smoke snapshots are temporary ignored test data. No provider key, model or Ollama server is needed.

</details>

<a id="offline-normalization-and-finalization"></a>
<details>
<summary><strong>Offline normalization and finalization</strong></summary>

After local registration or an online fetch/extraction, process the returned provisional version ID, or omit IDs to process the latest candidate of every registered source:

```powershell
.\.venv\Scripts\techdocqa.exe process ver_ID --json
.\.venv\Scripts\techdocqa.exe process --json
```

`process` accepts the same `--config`/`--profile` flags and never fetches a URL or contacts a provider. Local sources must still match their registered bytes at first processing; afterward verified immutable snapshots support offline reruns. PDF parsing and normalization run inside a terminating worker using the configured deadline. Processing runs expose `stage=normalization` with the existing outcomes/results/errors and exit rules. Online manifest-export warnings exit 1 without discarding committed versions.

Prose uses LF, Unicode NFC and conservative whitespace cleanup. Headings, paragraphs, lists and Markdown hard breaks retain structure. Explicit HTML code, Markdown fences, inline backticks and indented code remain verbatim, including code Unicode and newlines. PDF page-edge boilerplate and vocabulary-supported line-break hyphenation use documented deterministic rules. See the complete [normalization/hash/version policy](../docs/DECISIONS.md#phase-3b-normalization-and-finalization-2026-10-22).

`raw_hash` always hashes original bytes. `content_hash` hashes UTF-8 normalized text (ordered PDF pages joined by two LF characters); metadata is separate. Changed normalized text finalizes the new candidate and supersedes the previous active version atomically. Equivalent normalized text resolves to the existing finalized version; the byte candidate and its source provenance/history stay available without an extra finalized version. Different sources retain distinct identities and authoritative `duplicate_of` links. Failed processing retains the prior active version; the next run recovers interrupted attempts.

`status`/`list` still show the latest requested byte candidate, which can be failed or a nonfinalized duplicate. A duplicate's `processing.resolved_version_id` identifies its finalized content version; `history` exposes all candidates and active flags. `normalized` means eligible for later processing, not indexed/searchable. Finalized files remain private under `data/processing` and local byte snapshots under `data/local`; no document bodies enter SQLite. Older application readers cannot read the new metadata fields.

</details>

<a id="indexing-and-search"></a>
<details>
<summary><strong>Indexing and search</strong></summary>

Requires the local Ollama service with the pinned `nomic-embed-text:latest` for embedding. Run after `chunk`:

```powershell
.\.venv\Scripts\techdocqa.exe index --json
.\.venv\Scripts\techdocqa.exe search "What does linger.ms do?" --mode vector --technology "Apache Kafka" --top-k 5
.\.venv\Scripts\techdocqa.exe search linger.ms --mode bm25
.\.venv\Scripts\techdocqa.exe search --mode bm25 -- --flag-name
.\.venv\Scripts\techdocqa.exe index --rebuild
.\.venv\Scripts\techdocqa.exe search "What does linger.ms do?" --mode hybrid
.\.venv\Scripts\python.exe scripts\fetch_reranker.py
.\.venv\Scripts\techdocqa.exe search "What does linger.ms do?" --mode hybrid --rerank
```

`--mode hybrid` runs both searches over the same filters and fuses them by reciprocal rank (`rrf-v1`). Each result keeps both ranks, scores and relevances. If one retriever fails at run time, the other's results come back with `degraded: true` and `failed_retriever`; if both fail, the search fails.

`--rerank` sends at most 20 candidates to the cross-encoder `cross-encoder/ms-marco-MiniLM-L6-v2` and reorders them by its score. It runs on CPU through `onnxruntime`, with no torch. `scripts\fetch_reranker.py` downloads the model's three pinned files once, from huggingface.co at the pinned revision, into `data\models`, and checks each SHA-256. After that, reranking runs offline. A missing or altered file, or any reranker error, leaves the unreranked order with `degraded: true`. Reranking is off unless `[retrieval] rerank` or `--rerank` turns it on. The model's weights are Apache-2.0, but it was trained on MS MARCO, whose terms describe the data as for non-commercial research.

`index` embeds only chunks without a stored vector, so a repeat run needs no provider. `--rebuild` restores the whole vector index from stored vectors, also with no model call. BM25 needs no provider and serves chunked versions straight away; vector search needs `index` first. Filters are `--document-id`, `--technology`, `--category` and `--entity`; `--entity` matches only after `enrich` has run (see [NLP enrichment](#nlp-enrichment)). Unfiltered search includes every active document, including any private ones you have indexed. After changing the embedding model, run `chunk` and then `index`; each model keeps its own collection.

`search` prints matching chunk text. Everything stays on this machine under the Ollama profile. A one-off CLI search takes about 4 to 5 seconds, including startup. Known limits and measured results are in the [Phase 5 report](../docs/PHASES.md#phase-5-status).

</details>

<a id="smoke-benchmark"></a>
<details>
<summary><strong>Smoke benchmark</strong></summary>

Requires Ollama for vector mode; BM25 mode needs no provider.

```powershell
.\.venv\Scripts\techdocqa.exe eval
.\.venv\Scripts\techdocqa.exe eval --mode bm25
.\.venv\Scripts\techdocqa.exe eval --report-dir reports\evaluation
.\.venv\Scripts\techdocqa.exe eval --dataset datasets\benchmark_full.jsonl --mode bm25 --mode vector --mode hybrid --mode hybrid+rerank
```

`--mode` can be repeated, up to all four configurations. The report then adds Precision@K and nDCG@K, per-technology tables, and paired bootstrap intervals for hybrid against vector and for reranked against unreranked hybrid. [The full benchmark](../datasets/benchmark_full.jsonl) is the 30 smoke questions plus 20 held-out ones. Refusal thresholds are calibrated on smoke only, so on the full benchmark the refusal proposals are descriptive, and no configuration section is offered.

`eval` runs [the smoke questions](../datasets/benchmark_smoke.jsonl) through the same search as `search`, limited to the documents the [frozen manifest](../datasets/corpus_manifest.json) includes for evaluation, so the private DDIA supplement is left out. It prints a JSON summary and writes a JSON and a Markdown report, by default to the ignored `data\evaluation`. Reports contain chunk IDs, not chunk text. Two runs on unchanged inputs print the same `results_fingerprint`.

Each report also has a **Refusal calibration** section. For each mode it shows the top relevance of answerable and unanswerable questions, a proposed threshold, how many questions that threshold would pass or refuse, and leave-one-out errors as a check for small samples. It also shows how the active thresholds judge this run. Nothing changes until you copy the proposed `[retrieval.sufficiency.<mode>]` section into your configuration. The run that proposed it is then the calibration run, and its ID appears in every answer. Run `eval` again after changing the embedding model, BM25 settings or the corpus; until you adopt new thresholds, `ask` answers in that mode ungated and warns `SUFFICIENCY_CALIBRATION_STALE`.

Labels point at a document and a quoted passage, not at chunk IDs, so they survive re-chunking. If you withdraw or delete a labeled document, the next run flags its questions and leaves them out of the metrics; the benchmark file is not changed. Review status and the reviewer checklist are in the [review log](../datasets/review_log.md).

</details>

<a id="asking-questions"></a>
<details>
<summary><strong>Asking questions</strong></summary>

Requires Ollama with `qwen3:1.7b`; vector mode also needs `nomic-embed-text`.

```powershell
.\.venv\Scripts\techdocqa.exe ask "What is the default transaction isolation level in PostgreSQL?" --text
.\.venv\Scripts\techdocqa.exe ask "What does linger.ms do?" --mode bm25 --technology "Apache Kafka"
.\.venv\Scripts\techdocqa.exe eval --answers 10 --report-dir reports\evaluation
.\.venv\Scripts\techdocqa.exe eval --refusal --report-dir reports\evaluation
powershell -ExecutionPolicy Bypass -File scripts\cli_smoke.ps1
```

`ask` retrieves the top 5 chunks and keeps as many as fit the model's 8,192-token window. It then checks them against the relevance threshold calibrated for the retrieval mode. If the best kept chunk is below it, the answer is `no_evidence` / `LOW_RELEVANCE` and no model call is made. Otherwise the model is asked to answer only from the chunks and cite them as `[C1]`, `[C2]` and so on. Each citation is checked against the chunks actually supplied, and its title, section, page and source come from the registry, never from the model.

With `--text` it prints the status, the answer and the numbered citations; without it, JSON. The status is `answered`, `no_evidence` or `generation_error`. `no_evidence` means nothing matched, nothing was relevant enough, the model said the sources are insufficient, or no citation was valid. `generation_error` means a model or index failure, with a reason code and exit code 1. Every response shows the thresholds it used and their calibration run under `sufficiency`, and whether a model call was made under `llm_called`. The filters are the same as for `search`. Like `search`, `ask` includes every active document, including any private ones you have indexed, so a question the public documents cannot answer may still be answered from those.

Questions and document text stay on this machine. Each question adds a line to the ignored `data\logs\qa.jsonl` with chunk IDs, configuration IDs, the sufficiency result and timings; the question and answer appear there only as hashes. The first answer after Ollama loads the models took 44 s in one measurement, within the 60 s timeout; a timeout returns a retryable `LLM_TIMEOUT`.

`eval --answers 10` answers 10 smoke questions from the public reference and writes a report with an empty review column for AC-16.6. A review sheet with the cited chunk text is written to the ignored `data\evaluation`. After filling in its Supported column with `yes`, `partly` or `no`, `eval --record-review <sheet> --reviewer <name>` copies the ratings into the report and judges AC-16.6. With `--seed S`, `eval --answers N` instead runs the FR-19.3 review. It shuffles the answerable questions once with that seed and asks them in order until N have an answer with a citation. Its sheet has Faithful and Relevant columns, and the report counts both ratings. `eval --refusal` asks all 30 smoke questions and reports AC-18.1 and AC-18.2. Both load the chat model first, so a cold start does not count against the first answer. `scripts\cli_smoke.ps1` runs ingest, process, chunk, index, search, ask, withdraw and ask again with the real models, in a temporary directory that it deletes afterwards.

</details>

<a id="nlp-enrichment"></a>
<details>
<summary><strong>NLP enrichment (Phase 9)</strong></summary>

Run after `index`. Entities and keyphrases need no provider; classification uses the stored chunk vectors and embeds only the category descriptions, so it needs Ollama with `nomic-embed-text`.

```powershell
.\.venv\Scripts\techdocqa.exe enrich
.\.venv\Scripts\techdocqa.exe enrich ver_ID
.\.venv\Scripts\techdocqa.exe enrichment doc_ID
.\.venv\Scripts\techdocqa.exe enrichment doc_ID --chunk-id chunk_ID
.\.venv\Scripts\techdocqa.exe search "consumer groups" --mode bm25 --entity "Apache Kafka"
.\.venv\Scripts\techdocqa.exe eval --enrichment --report-dir reports\evaluation
.\.venv\Scripts\techdocqa.exe eval --enrichment --gold-dir datasets\nlp\round2 --fixtures datasets\nlp\out_of_topic.jsonl --report-dir reports\evaluation
```

The first `enrich` upgrades the registry to schema version 3, after an automatic, verified backup to `registry.sqlite3.pre-v3.bak`. Unchanged documents are skipped on later runs, and re-chunking, withdrawal and deletion leave no stale entities or categories. `enrichment` is read-only.

- **Entities (FR-07)** come from [config/gazetteer.toml](../config/gazetteer.toml) and regex rules for identifiers and protocols. Ambiguous names such as `Spark` or `Kafka` count as exact only in context, and only verified entities feed `--entity`.
- **Keyphrases (FR-08)** are the top 10 per document from the `technical-ngrams-v1` policy: 1- and 2-word terms ranked by frequency, with a bonus for two-word terms and gazetteer terms. `[enrichment] keyphrase_policy = "rake"` selects RAKE instead, which needs the `nlp` extra. Keyphrases are stored and shown but do not enter BM25.
- **Entity rules v2:** gazetteer types follow the annotation guidelines' type table, a file given with a directory is extracted by its name (`kafka-topics.sh`), and upper-case SQL keywords used as syntax are identifiers.
- **Categories (FR-09)** compare each document with the four configured category descriptions. A document whose best score is below the calibrated `unclassified_threshold` gets `unclassified`. The threshold applies only while its `similarity_config_id` matches, so a new embedding model or an edited description leaves documents `not_calibrated` until `eval --enrichment` proposes a new one. A user category always takes precedence.
- **Sentences (FR-06)** use the P0 rules for chunking. `[chunking] segmentation = "spacy"` selects the spaCy policy, which re-chunks every document. On the gold set it ties the rules (F1 0.989), so chunking stays on the rules.

Unfiltered search and `ask` read no enrichment data, so the Phase 6 to 8 results stay valid. `eval --enrichment` reads the registry and changes nothing. It scores the frozen gold sets in `datasets/nlp` (round 1, now development data) or `datasets/nlp/round2` (the held-out round 2), classifies the [out-of-topic fixtures](../datasets/nlp/out_of_topic.jsonl) in memory, proposes the `unclassified` threshold and checks the enriched corpus. A gold set that is not frozen yet is reported as awaiting data. The gold sets are prepared with `datasets/nlp_gold.py`; their state is in the [review log](../datasets/nlp/review_log.md).

</details>

<a id="withdrawing-and-deleting-documents"></a>
<details>
<summary><strong>Withdrawing and deleting documents</strong></summary>

```powershell
.\.venv\Scripts\techdocqa.exe withdraw doc_ID --reason "License under review"
.\.venv\Scripts\techdocqa.exe delete doc_ID --reason "Rights expired" --yes
```

`withdraw` removes a document from both searches immediately and keeps its data. Re-ingesting the same content reactivates it; run `index` to return it to vector search. `delete` cannot be undone: it removes the document's registry records, chunks, vectors, index entries and stored snapshots, while keeping anything another source shares. It does not touch your original files or registry backups.

</details>
