# Proposed repository structure

Status: proposal, 2026-10-09. Source: [requirements](../TechDocQA_Requirements_v2.md), contents Revision 3. Only the five planning documents are created now. Paths below are future components, not claims that code exists. Add a module when its roadmap phase needs it; responsibilities may share a small module until size warrants separation.

Current checkpoint: the original tree below remains the target. Phase 1 now adds packaging, settings.py, schemas.py, a configuration-only cli.py, tests, local config/profile, draft manifest and setup/verification documentation. Remaining ingestion/processing/indexing/retrieval/answering/evaluation modules have not been created. No large empty module tree is introduced; see [Phase 1 checkpoint](PHASE_1_STATUS.md).

```text
TechDocQA/
  TechDocQA_Requirements_v2.md    # original source, unchanged
  README.md                     # setup, hardware, provider privacy, commands
  pyproject.toml                # package, CLI entry point, constrained direct deps
  requirements.lock.txt         # proposed exact transitive lock for pip
  .gitignore                    # secrets, virtualenv, local corpus/runtime outputs
  .env.example                  # placeholders only, if .env support is chosen
  config/
    default.toml                # nonsecret limits, storage and retrieval defaults
    profiles/                   # OpenAI/Ollama nonsecret model settings
  src/techdocqa/
    __init__.py
    cli.py                      # commands, JSON output, exit codes
    settings.py                 # validated TOML/environment settings
    schemas.py                  # typed section 8 requests/results/errors
    registry.py                 # SQLite, versions, attempts, events, provenance
    ingestion/
      pipeline.py               # bounded, rerunnable stage coordination
      loaders.py                # framework loaders and format-specific cleaning
      normalization.py          # deterministic normalization, hashes, text mapping
      safety.py                 # path/signature/size/page/timeout validation
    processing/
      segmentation.py           # P0 rules, later P1 NLP spans
      chunking.py               # framework splitters, source-aware chunk metadata
      enrichment.py             # P1 entities, keyphrases, classification
    indexing/
      embeddings.py             # framework embedding construction, validation/cache
      vector_store.py           # local persisted framework vector integration
    retrieval/
      lexical.py                # framework BM25 and technical token preprocessing
      search.py                 # common mode/filter/result orchestration
      fusion.py                 # P1 RRF, if framework adapter alone is insufficient
      reranking.py              # P1 optional framework reranker
    answering/
      generation.py             # configured framework QA chain/context budget
      citations.py              # labels, stored sources, citation verification
      sufficiency.py            # calibrated checks and refusal reasons
    evaluation/
      dataset.py                # frozen manifest, questions, anchor resolution
      metrics.py                # recall/MRR, later precision/nDCG
      runner.py                 # reproducible results, calibration and reports
  datasets/
    corpus_manifest.json        # source/license, byte and normalized hashes
    benchmark_smoke.jsonl       # 30 reviewed stable-anchor questions
    benchmark_full.jsonl        # P1 <=50, contains smoke set
    review_log.md               # second-person review and label disagreements
  tests/
    fixtures/                   # small synthetic data only, separate from corpus
    test_*.py                   # FR test targets from traceability matrix
  docs/
    requirements_traceability.md
    TECHDOCQA_SDD.md
    REPOSITORY_STRUCTURE.md
    DECISIONS.md
    IMPLEMENTATION_ROADMAP.md
  deployment/
    local_setup.md              # later clean-machine and optional local model setup
  reports/
    evaluation/                # reviewed redacted reports suitable for committing
  data/                         # ignored runtime artifacts, configurable root
    corpus/                     # actual permitted reference files
    snapshots/                  # original bytes, extracted/normalized versions
    registry.sqlite3
    vectors/                    # collection per embedding/config profile
    embeddings/                 # rebuildable cache with reference ownership
    runs/                       # private per-run records and redacted logs
```

## Responsibility and dependency boundaries

`src/techdocqa` is the installed package, avoiding imports from repository root. Settings and schemas stay small and shared; component boundaries use framework interfaces and typed records, not a new plugin framework. Registry is authoritative; vector/BM25 indexes are derived. Loading and splitting use LangChain with only required preservation/safety adapters. Retrieval accepts query/filter records and returns source-bearing candidates; answering consumes these and maps verified labels to registry sources. Evaluation imports the same search/QA functions used by the CLI, preventing benchmark-only behavior.

`config` contains no credentials. Environment variables hold secrets; `.env`, if supported, is ignored. `datasets` contains manifest and versioned labels, not user documents or paid-provider logs. `tests/fixtures` includes DS-05 edge cases plus source acceptance fixtures; actual corpus licensing determines whether files can be redistributed. `data` is local, rerunnable state; recorded hashes and settings enable reproducibility. `reports` commits selected nonsensitive evidence, with costs/models/hardware recorded when measured.

`deployment` is documentation for one developer machine, not service infrastructure. No API endpoints or mandatory container files are proposed. URL ingestion and web UI paths are deliberately deferred until P2 is approved. Health/retry functionality can extend CLI and existing modules without creating a monitoring service.

## Creation sequence and constraints

Phase 1 introduces packaging, settings, schema tests and setup documentation after approval. Ingestion and registry modules appear in phases 2–3, chunking/indexing in 4–5, evaluation in 6, answering in 7–8, P1 components in 9–10, and operational evidence in 11. See [roadmap](IMPLEMENTATION_ROADMAP.md) for dependencies and [decisions](DECISIONS.md) for unresolved identity and response schemas.

Lock dependencies only after verifying a compatible Python/framework set. Use minimal provider-specific integrations and optional P1 extras; neither dependency installation nor placeholder module creation is part of this task. A dedicated Git repository is proposed because the current Git root is the user home; no Git initialization or ancestor changes are performed now.
