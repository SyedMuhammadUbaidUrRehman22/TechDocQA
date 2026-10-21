# Phase 1 foundation checkpoint

Current review: 2026-10-21. **Foundation verified; Phase 1 remains partially complete.** Corpus, hardware, budget and reviewer gates remain open; models were deliberately deferred. Phase 2 has subsequently implemented the identified validation gaps and registration slice; see [actual Phase 2 evidence](PHASE_2_STATUS.md). The setup and review evidence below is historical, not a claim that its former defects remain unfixed.

User approval: roadmap Phase 1 approved, LangChain selected, open source model to be decided later; publish foundation to the specified GitHub repository. This is interpreted as roadmap Phase 1, not priority P1 enhancement implementation.

## Established files

- Dedicated local Git repository preserving the remote initial README commit.
- Python src package, setuptools packaging, dependency constraints and an exact tested dependency lock.
- Nonsecret TOML defaults and local Ollama profile; model names and context window intentionally unset.
- Pydantic validation for settings, initial search/question requests and section 8.4 errors.
- Configuration-only CLI (`config-check`); no ingestion/search/ask command is advertised as implemented.
- Offline settings/schema/CLI tests, local setup instructions and a clearly draft corpus manifest.

Concrete framework/provider loading is deferred. LangChain and its Ollama integration are package dependencies; no model call or provider service is used. See [official LangChain Ollama integration documentation](https://docs.langchain.com/oss/python/integrations/providers/ollama/) for the integration boundary; an installed adapter does not imply a running server or selected model.

## Remaining Phase 1 gates

Phase 1 foundation completion does not mean its corpus/model/hardware gates are complete. Corpus selection remains 15–30 permitted documents across 3–5 technologies and required format coverage; files, licenses and hashes are not fabricated. Hardware, budget and second reviewer are unset. Model selection was explicitly deferred by the user. Exact embedding dimension, model revision/context/input limits and model licenses must be recorded when selected.

LangChain approval resolves the framework choice. Open source model selection establishes the local development direction; it does not silently delete C-07/NFR-08/FR-22 provider-portability obligations. Confirm an explicit source amendment later if OpenAI support is to be removed. No OpenAI adapter/key setup is added now.

Registry/version/chunk identity, active-state semantics and scoring questions Q-02–Q-16 remain open before their affected phases. Only request/error schemas are introduced now, avoiding unapproved persistence/QA response semantics. Allowed directories in settings are configuration only; their security enforcement is implemented in Phase 2.

## Verification

Executed on Windows with Python 3.13.3:

- Installed the constrained foundation into `.venv` and generated `requirements.lock.txt` from actual resolved packages (no editable/local paths in the lock).
- Verified LangChain 1.4.4, langchain-core 1.6.9, langchain-ollama 1.1.0, Pydantic 2.14.0 and pytest 9.1.1. Imported LangChain, ChatOllama, OllamaEmbeddings, framework Document and the project package successfully, without invoking any provider.
- Foundation tests: **13 passed**. Initial attempts exposed an inaccessible system pytest temp directory and a missing scratch-parent directory; the final configuration uses the ignored repository-root `.pytest_tmp` and passes.
- `pip check`: no broken requirements. `config-check`: valid configuration, incomplete model selection, provider connectivity not checked. The test for `--require-models` confirms its expected failure with a standard JSON error while models are unset.
- Created a separate fresh `.venv-verify`, installed the exact lock and editable project without dependency re-resolution/build isolation, then reran the tests: **13 passed**. Its complete frozen dependency inventory equals the lock. CLI and `pip check` also passed there.
- Checked all original FR titles, priority/dependency declarations and AC lines still match traceability, and local README/docs/deployment/dataset links resolve. Original source hash remains `48EF8D3069F90C0D33A3F736CC3F3DD685734C2A59B4CEEABCCA5FC625869B59`.

Python 3.11/3.12 and non-Windows installations are not verified. No ingestion, provider integration, benchmark, model quality, retrieval performance, API cost or hardware sufficiency is claimed. Git push is verified separately against the remote commit after committing these files.

## Review on 2026-10-21

- Reran the existing foundation suite in `.venv`: **13 passed**. Both existing environments pass `pip check` and `config-check`, and both frozen package inventories still equal the exact lock. No fresh installation was performed; the second environment's test suite was not rerun in this review.
- Confirmed that the draft manifest contains **0 documents and 0 technologies**. No DS-05 ingestion/parser fixtures exist yet. Corpus selection and licenses/hashes are unfinished Phase 1 work; synthetic fixtures belong to Phases 2–3. Model deferral is intentional. Hardware/budget and reviewer choices remain needed before their integration/evaluation gates.
- Reproduced a settings gap: an empty string in `allowed_directories` is accepted and resolves to the configuration directory. Reject blank entries before ingestion safety is implemented.
- Reproduced a CLI gap: invalid arguments use argparse usage text/exit 2 rather than section 8.4 JSON, and can echo argument values. Extend sanitized standard errors when adding ingest/status. Existing configuration-error redaction tests do not cover argument errors.
- Registry lifecycle, source-key collisions and provisional registration versus normalized duplicate versions (Q-02/Q-04/Q-05) remain unsettled. The Phase 2 plan lists concrete contracts and verification before registry coding.
- All 24 FRs and 111 AC lines are intact, and all AC lines match traceability. The requirements file already has an uncommitted table-row line-break edit, preserved by this review. Its current working SHA-256 is `D458DDB2175D507004806738D3F87DE41405D40D39676B52995E07DB3D479949`; the original source hash above describes the earlier checkpoint.

This review produces a Phase 2 plan and documentation corrections. It does not fix the application gaps or implement registration, and it does not reverify remote publication. The next implementation slice is registry/registration/local safety; complete corpus selection in parallel without claiming all of Phase 1 is done.
