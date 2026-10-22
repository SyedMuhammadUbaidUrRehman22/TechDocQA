# Local development setup

Use Python 3.11–3.13; Phase 2 is verified on Windows Python 3.13.3. From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\techdocqa.exe config-check
```

The committed lock records the tested foundation dependencies including test/build tools. It was resolved on Windows/Python 3.13; other platforms/interpreters require their own clean installation verification. After deliberately updating dependency constraints, resolve them in a fresh environment, run tests/import checks and regenerate the exact lock; do not casually update a single transitive pin.

Tests use ignored `.pytest_tmp` under the repository as their disposable temporary directory. Pytest replaces that directory between runs; keep only test scratch data there. This avoids the existing access-denied system pytest temp directory on this development machine.

LangChain is selected. The local profile selects Ollama as the proposed serving interface, while the open source chat and embedding models remain unset. Phase 2 provides byte registration and SQLite status/history without a provider. No Ollama server, model weights, vector database, text extraction or QA integration is provisioned. `config-check --require-models` deliberately fails until both model names and context_window are configured; it checks selection only, not provider connectivity or model quality. Checkpoint for actual model provisioning is roadmap Phase 5/7.

Set model names in TOML or use TECHDOCQA_CHAT_MODEL and TECHDOCQA_EMBEDDING_MODEL; these override TOML. `--profile config/profiles/ollama.toml` overlays sections. Relative storage/allowlist paths resolve against the base TOML file. Phase 2 enforces allowed-directory containment against open file handles, byte limits/signatures and bounded PDF page inspection. Blank paths fail configuration; missing input roots are allowed at setup and never auto-created, while existing nondirectory/inaccessible roots fail safely. Credentials never belong in configuration files or committed source. OpenAI remains an unimplemented portability requirement, not the selected development provider.

For a registration smoke run, create a permitted local `data/corpus` directory yourself and place a supported file there, then run `techdocqa ingest data/corpus --json`, `techdocqa list --json`, `techdocqa status --document-id <returned-id> --json` and `techdocqa history <returned-id> --json` through `.venv/Scripts/techdocqa.exe`. These are registration/status operations, not extraction or indexing. See [README syntax](../README.md#registration-commands) and [implemented decisions](../docs/DECISIONS.md#implemented-phase-2-contracts-2026-10-21).

The registry initializes without destroying existing records at `<data_directory>/registry.sqlite3`. A persistent OS lock file permits one registration runner; a competing runner gets retryable `REGISTRY_BUSY`. A subsequent ingestion recovers interrupted runs while preserving committed successes. Treat the database as local private runtime data and do not commit it. Do not delete lock files while a runner is alive. Unsupported/newer registry schema versions fail safely rather than resetting data.

Handle validation has been executed on Windows (including file symlinks and directory junctions). A Linux `/proc/self/fd` path exists in the code but is not verified here; other platforms fail closed with `PLATFORM_NOT_SUPPORTED` rather than weakening path checks. Python 3.11/3.12 and non-Windows installation remain unverified.

Hardware needs, model licensing, context/token limits and benchmark cost remain undecided until model/corpus selection. No performance or quality claim is made.

Phase 3A adds controlled online HTML ingestion through the same installed `techdocqa ingest` command. See [online CLI/catalog instructions](../README.md#controlled-online-ingestion) and [network policy](../docs/PHASE_3A_STATUS.md#network-and-storage-policy). No API key or provider server is required. The default suite blocks outbound traffic; real tests require `python -m pytest tests/test_online.py -m live --live --basetemp=.tmp/phase3a-live` explicitly. HTTPS proxies are intentionally not used: the fetcher pins a validated public IP and verifies TLS for the original hostname. Do not disable TLS verification or widen scopes to work around a network failure. Keep the configured data directory private on a filesystem supporting hard links; only Windows/Python 3.13.3 has been executed here.

Phase 3B adds `techdocqa process [version_ids ...] --json` after registration/extraction; without IDs it processes each source's latest byte candidate. It runs fully offline, reuses verified Phase 3A extractions, and captures hash-verified local bytes before framework loading. Preserve the entire private data directory, including local and processing snapshots, alongside SQLite for recovery. Schema/dependencies remain unchanged; downgrading readers after new metadata is written is unsupported. See [normalization/version semantics](../docs/DECISIONS.md#phase-3b-normalization-and-finalization-2026-10-22) and [checkpoint](../docs/PHASE_3B_STATUS.md).
