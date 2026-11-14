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

Measured hardware needs, timings and the clean-clone check are in the [Phase 11 report](../docs/PHASE_11_STATUS.md). The commands themselves are described in the [README](../README.md#command-guide).
