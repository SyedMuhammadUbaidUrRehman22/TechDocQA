# Proposed repository structure

Phase 9 update 2026-11-12: actual additions are the package `enrichment/{entities,keyphrases,classification,pipeline}.py` rather than one `enrichment.py`, `evaluation/enrichment.py` for `eval --enrichment`, the spaCy policy inside `segmentation.py`, `config/gazetteer.toml`, `datasets/nlp_gold.py` with `datasets/nlp/` (guidelines, review log, out-of-topic fixtures and, once frozen, the gold sets), `scripts/run_tests.py` and `tests/test_{entities,keyphrases,classification,enrichment,enrichment_eval,nlp_gold}.py`. Annotation sheets hold document text and stay in the ignored `data/nlp`. `eval --enrichment` writes `enrichment_*` reports next to the other evaluation reports. See [Phase 9](PHASE_9_STATUS.md).

Phase 8 update 2026-11-04: actual additions are `answering/sufficiency.py`, `tests/test_sufficiency.py` and `scripts/cli_smoke.ps1`, the AC-22.3 real-model CLI workflow. Thresholds live in `[retrieval.sufficiency.*]` in `config/default.toml`. `eval --refusal` writes `refusal_*` reports next to the other evaluation reports. No calibration or context-integration module was split out of `generation.py`, because the gate is a few lines there. See [Phase 8](PHASE_8_STATUS.md).

Phase 7 update 2026-11-03: actual additions are `answering/{generation,citations}.py`, `evaluation/answers.py`, `tests/test_{generation,citations}.py` and the `tests/fixtures/prompt_injection.md` fixture. `sufficiency.py` waits for Phase 8. The query log is the ignored `data/logs/qa.jsonl`; answer review sheets with cited text go to the ignored `data/evaluation`. See [Phase 7](PHASE_7_STATUS.md).

Phase 6 update 2026-11-03: actual additions are `evaluation/{dataset,metrics,runner}.py`, `datasets/{benchmark_smoke.jsonl,review_log.md}`, `reports/evaluation/` and `tests/test_evaluation.py`. Run reports go to the ignored `data/evaluation` unless `--report-dir` names another directory. See [Phase 6](PHASE_6_STATUS.md).

Phase 5 update 2026-11-02: actual additions are `indexing/{embeddings,vector_store,pipeline,lifecycle}.py`, `retrieval/{lexical,search}.py`, `datasets/verify_index.py` and `tests/test_indexing.py`. Runtime vectors live in the ignored registry and `data/index/chroma`. See [Phase 5](PHASE_5_STATUS.md).

Phase 4 update 2026-10-24: actual additions are package-root `segmentation.py` and `chunking.py`, `ingestion/chunks.py`, and `tests/test_{segmentation,chunking}.py`. They reuse the existing worker, registry JSON metadata and atomic snapshot helpers. Runtime chunk text/spans live under ignored `data/chunking/artifacts`, with active pointers in the registry. No SQL migration or empty indexing module tree was added. See [Phase 4](PHASE_4_STATUS.md).

Status: proposal, 2026-10-09. Source: [requirements](../TechDocQA_Requirements_v2.md), contents Revision 3. Only the five planning documents are created now. Paths below are future components, not claims that code exists. Add a module when its roadmap phase needs it; responsibilities may share a small module until size warrants separation.

Current checkpoint, 2026-10-21: Phase 2 adds `registry.py`, `errors.py`, `privacy.py`, `ingestion/{pipeline,safety,pdf_check}.py`, registration schemas, CLI operations and offline ingestion/registry/safety/CLI tests with generated fixtures. `DEVELOPMENT_LOG.md`, `docs/PHASE_2_STATUS.md` and `docs/LANGCHAIN_INGESTION_PLAN.md` record evidence and the loader boundary. Remaining loaders/normalization/processing/indexing/retrieval/answering/evaluation modules are not created. The tree below remains the later target; no empty module tree is introduced.

Phase 3A adds `ingestion/urls.py` (syntax/scope policy), `fetching.py` (pinned HTTPS), `html.py` (LangChain extraction adapter), `online_worker.py` (isolated bounded processing) and `online.py` (catalog selection/snapshots/registry/manifest coordination). Catalog entries use the existing `config/default.toml`; no second source catalog exists. `tests/test_online.py` contains mocked offline and opt-in live tests. `data/online/{snapshots,extracted}` and its generated corpus-manifest projection remain ignored runtime artifacts. See [Phase 3A checkpoint](PHASE_3A_STATUS.md).

Phase 3B adds `normalization.py`, `ingestion/{loaders,processing,processing_worker}.py`, transactional finalization in the existing registry, the `process` CLI command and `tests/test_{normalization,loaders,versioning}.py`. Local raw snapshots use `data/local/snapshots`; extracted Documents JSON, normalized UTF-8 text and normalized Documents JSON use `data/processing/{extracted,normalized,documents}`. All remain ignored. No chunk/index/retrieval modules exist yet. See [Phase 3B checkpoint](PHASE_3B_STATUS.md); the proposed tree below is historical and normalization actually lives at the package root.

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
