# Local development setup

Use Python 3.11–3.13; the foundation is verified on Windows Python 3.13.3. From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\techdocqa.exe config-check
```

The committed lock records the tested foundation dependencies including test/build tools. It was resolved on Windows/Python 3.13; other platforms/interpreters require their own clean installation verification. After deliberately updating dependency constraints, resolve them in a fresh environment, run tests/import checks and regenerate the exact lock; do not casually update a single transitive pin.

Tests use ignored `.pytest_tmp` under the repository as their disposable temporary directory. Pytest replaces that directory between runs; keep only test scratch data there. This avoids the existing access-denied system pytest temp directory on this development machine.

LangChain is selected. The local profile selects Ollama as the proposed serving interface, while the open source chat and embedding models remain unset. No Ollama server, model weights, vector database, ingestion engine or QA integration is installed by this foundation. `config-check --require-models` deliberately fails until both model names and context_window are configured; it checks selection only, not provider connectivity or model quality. Checkpoint for actual model provisioning is roadmap Phase 5/7.

Set model names in TOML or use TECHDOCQA_CHAT_MODEL and TECHDOCQA_EMBEDDING_MODEL; these override TOML. `--profile config/profiles/ollama.toml` overlays sections. Relative storage/allowlist paths resolve against config/default.toml. Merely declaring allowed directories does not enforce parser/path safety; that implementation is Phase 2. Credentials never belong in configuration files or committed source. OpenAI remains an unimplemented portability requirement, not the selected development provider.

Hardware needs, model licensing, context/token limits and benchmark cost remain undecided until model/corpus selection. No performance or quality claim is made.
