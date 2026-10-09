# TechDocQA
TechDocQA is a domain-specific RAG project for answering software and data engineering questions from technical documentation with source citations. The planned system uses LangChain, semantic search, BM25 and NLP.

## Current status

Roadmap Phase 1 foundation is established: an installable Python package, constrained dependencies, validated configuration, initial request/error contracts, a configuration-check CLI and offline tests. **Document ingestion, indexes, retrieval, model calls, answering and benchmarks are not implemented.** No FR is claimed complete by the foundation.

LangChain is approved. An open source model will be selected later; Ollama is the configured local serving profile and both chat/embedding model names remain unset. The original source still specifies OpenAI/Ollama portability, so OpenAI support remains a later requirement pending clarification if the project becomes local-only. No model weights or provider service are required for foundation tests.

## Setup

Use Python 3.11–3.13; Windows Python 3.13.3 is the verified development environment. From this repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\techdocqa.exe config-check
```

`config-check` validates settings without contacting providers. `config-check --require-models` intentionally fails while model names/context window are unset; it never verifies connectivity or model quality. TOML settings are in [config/default.toml](config/default.toml). TECHDOCQA_CHAT_MODEL and TECHDOCQA_EMBEDDING_MODEL override the model names; context_window must be selected in TOML. Relative paths resolve against the base configuration file.

Keep credentials out of TOML, logs and version control. Local runtime data and virtual environments are ignored. Dependencies for parsing, vector storage, NLP and reranking will be added only in their implementation phases.

## Source and plan

The source filename says v2, but its contents identify **Revision 3**; those contents remain authoritative and unchanged.

- [Functional requirements](TechDocQA_Requirements_v2.md)
- [Traceability: all 24 FRs and 111 original acceptance criteria](docs/requirements_traceability.md)
- [Software Design Document](docs/TECHDOCQA_SDD.md)
- [Repository structure](docs/REPOSITORY_STRUCTURE.md)
- [Decisions and unresolved source questions](docs/DECISIONS.md)
- [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md)
- [Phase 1 checkpoint](docs/PHASE_1_STATUS.md)
- [Local development setup](deployment/local_setup.md)
- [Corpus preparation](datasets/README.md)

The corpus manifest is a draft, not evaluation data. Corpus documents/licenses, reference hardware, budget, reviewer, exact models and model performance remain unverified. Next is Phase 2 registry/registration/safety work, after resolving the recorded identity/status questions and corpus selection gates.
