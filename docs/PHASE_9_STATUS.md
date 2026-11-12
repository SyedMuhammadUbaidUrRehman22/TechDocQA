# Phase 9 P1 NLP enrichment

Implementation and evidence checkpoint 2026-11-12 on Windows, Python 3.13.3, local Ollama with `nomic-embed-text:latest`, spaCy 3.8.18 and `rake-nltk` 1.0.6. Phase 9 adds FR-07 entities, FR-08 keyphrases and FR-09 categories through `enrich`, the FR-06 P1 spaCy segmentation policy, and `eval --enrichment`, which measures all of them. It covers the [Phase 9 plan](PHASE_9_PLAN.md) under its [contracts](DECISIONS.md#phase-9-contracts-2026-11-07).

**Result:** everything that needs no human labels is built, run on the real corpus and met. On the 20 public documents, classification puts 19 of 20 in their manifest category: 0.95 against a target of 0.85, **met at the point estimate only**, because the 95% interval starts at 0.764. The cooking article and 3 other held-out out-of-topic fixtures are `unclassified`; the fifth, a LaTeX guide, is not. The real-corpus checks for AC-07.2, AC-07.3, AC-08.1 and AC-09.3 pass in both retrieval modes. Unfiltered retrieval is unchanged: the smoke `eval` fingerprint before and after `enrich` equals the Phase 8 baseline. **AC-06.4, AC-07.4 and AC-08.3 are not measured yet,** because they need the owner's gold labels, which are not done ([what remains](#what-remains)).

## What was added

The storage, commands and extractors were committed earlier (60458fc); this checkpoint adds the measurement, the threshold, the segmenter and the fixes listed under [Fixes](#fixes-found-while-completing-the-phase).

| Area | Behavior | Code |
|---|---|---|
| Storage and commands | Registry schema v3 with a verified pre-upgrade backup. `enrich [version_ids]` writes entities, keyphrases and categories in one transaction per document and skips unchanged ones. `enrichment DOC [--chunk-id]` shows them, read-only. | [registry.py](../src/techdocqa/registry.py), [pipeline.py](../src/techdocqa/enrichment/pipeline.py) |
| Entities (FR-07) | The frozen [gazetteer](../config/gazetteer.toml) plus regex rules for identifiers and protocols. Ambiguous names count as exact only in context. Only verified entities feed `--entity` in both modes. | [entities.py](../src/techdocqa/enrichment/entities.py) |
| Keyphrases (FR-08) | Top 10 per document with RAKE. Policy `rake-nltk-technical-v2` keeps contractions and possessives whole and drops Markdown emphasis underscores. A new `keyphrase_metric` setting chooses RAKE's word score. | [keyphrases.py](../src/techdocqa/enrichment/keyphrases.py) |
| Categories (FR-09) | Cosine between a document's mean chunk vector and each category description. The new `unclassified` threshold applies only while `similarity_config_id` names the active scale (policy, embedding profile and descriptions), as Phase 8 thresholds do. A stale threshold classifies nothing and warns `CLASSIFICATION_CALIBRATION_STALE`. | [classification.py](../src/techdocqa/enrichment/classification.py), [settings.py](../src/techdocqa/settings.py) |
| Segmentation (FR-06 P1) | `[chunking] segmentation = "spacy"` selects `spacy-technical-sentences-v1`: spaCy's tokenizer and rule-based sentencizer, then technical rules (below). The default, `"rules"`, keeps every existing chunking configuration ID. | [segmentation.py](../src/techdocqa/segmentation.py), [chunking.py](../src/techdocqa/chunking.py) |
| Measurement | `eval --enrichment` scores the gold sets, classifies the out-of-topic fixtures in memory, proposes the `unclassified` threshold and checks the enriched corpus. It writes nothing to the registry, index or configuration. | [enrichment.py](../src/techdocqa/evaluation/enrichment.py), [cli.py](../src/techdocqa/cli.py) |
| Fixtures | 10 out-of-topic texts written for this phase, 5 to calibrate and 5 held out, the cooking article among the held out. Six are non-technical and four are technical but off-category (CSS, Git, home Wi-Fi, LaTeX), so the threshold is not judged only on easy cases. | [out_of_topic.jsonl](../datasets/nlp/out_of_topic.jsonl) |
| Tests | `scripts/run_tests.py` runs the suite in four groups, one process each. An autouse fixture releases Chroma's cached clients after each test. | [run_tests.py](../scripts/run_tests.py), [conftest.py](../tests/conftest.py) |

### The spaCy policy's technical rules

The sentencizer proposes boundaries after `.`, `!` and `?`. The policy then applies five rules, each from the requirement's examples or the annotation guidelines, and none tuned on the gold sheet:

1. A blank line is a boundary, and so is a line that starts with a list marker. A single line break is not, because PDF and Markdown text is hard-wrapped.
2. A boundary needs whitespace before it, so `System.Console` and `end.Next` never split.
3. No boundary after abbreviations such as `e.g.`, `Fig.`, `vs.` or `Dr.`. `etc.` ends a sentence only before an uppercase word.
4. An opening quote or bracket left at the end of a sentence moves to the next one.
5. No boundary inside protected code.

Spans keep the P0 contract: half-open offsets that cover every character, so AC-06.1 to AC-06.3 hold for both policies.

## Fixes found while completing the phase

- **Registry migration hang (P9-8).** The v2 to v3 migration took its backup with SQLite's backup API from the connection that held `BEGIN IMMEDIATE`. SQLite returns `SQLITE_BUSY` to a backup whose source connection is in a write transaction, and Python's `backup()` retries that forever. So the first open of any v1 or v2 registry hung, including the real one, and so did three migration tests. The backup now reads through a second, read-only connection. The migrating connection still holds the write lock from before the copy until the commit but has written nothing yet, so the copy is exactly the state being migrated and nothing can commit in between. The reader is closed before the commit.
- **Two test bugs hidden by the hang.** A race test compared `sqlite3.Row` objects with tuples. The entity-filter test in `test_indexing.py` relied on a relative gazetteer path, so it failed when run on its own.
- **Test memory.** Chroma keeps every client it creates in a process-wide cache. Each test's temporary index stayed in memory, so `test_indexing.py` alone grew to 677 MB with 46 cached clients, and a single-process run of the whole suite exhausted a 12 GB machine. Releasing the clients after each test bounds this, and the runner returns memory between groups.

## Real-corpus run (2026-11-12)

| Step | Result |
|---|---|
| First open of the real registry | Migrated v2 to v3. The backup `data/registry.sqlite3.pre-v3.bak` is at v2, passes `integrity_check` and has the same row count in every table as a copy taken just before. The live registry is at v3 with every old table unchanged and five new empty tables. |
| Smoke `eval` before `enrich` | [eval_bfa563bc](../reports/evaluation/eval_bfa563bc8aa544e29cb839fb7f26c1b1.md): fingerprint `48ce89dc...a3af410`, equal to the Phase 8 baseline `eval_50d06f55`. |
| `verify_index.py --snapshot` | 20 queries recorded, 8 of 8 identifiers at rank 1. |
| `enrich` | 21 documents processed, 0 failed, in 21 s: 12,903 entities (12,737 verified) and 10 keyphrases per document. Classification `not_calibrated`, as expected. |
| `eval --enrichment` (calibration run) | [enrichment_eaf9c6a6](../reports/evaluation/enrichment_eaf9c6a675d647008a9a99a0944b1bab.md) proposed 0.649099. A second run gave the same value. |
| Threshold adopted | `unclassified_threshold`, `calibration_run_id` and `similarity_config_id` copied into [default.toml](../config/default.toml). `enrich` then classified all 21; a rerun skipped all 21. |
| Keyphrase policy v2 | `enrich` recomputed all 21, as a configuration change should. |
| Final `eval --enrichment` | [enrichment_96ba7374](../reports/evaluation/enrichment_96ba7374b2284057b4b34939026145d9.md), judged by the active threshold. |
| Smoke `eval` after `enrich` | [eval_d6b2ea04](../reports/evaluation/eval_d6b2ea04cee24c2f9b6d978a592a6b25.md): same fingerprint and metrics as before. |
| `verify_index.py --compare` | Top 5 identical in both modes. |

## Acceptance

| Criterion | Evidence | Result |
|---|---|---|
| AC-06.1 to AC-06.3 | `test_segmentation.py`, both policies | ✅ Met |
| AC-06.4 | `eval --enrichment` against the 50-sentence gold set, for both policies | ⏳ Awaiting the owner's review of the sentence draft |
| AC-07.1 | `test_entities.py` fixture | ✅ Met |
| AC-07.2 | Tests; real corpus: 5,598 entity rows on the 20 public documents, every chunk ID, document ID and both offsets valid | ✅ Met |
| AC-07.3 | Tests with `entity=Redis`; real corpus with `entity=PostgreSQL`: 20 of 20 results in each mode carry a verified PostgreSQL entity | ✅ Met |
| AC-07.4 | `eval --enrichment` against 20 labeled chunks | ⏳ Awaiting the owner's labels |
| AC-08.1 | Tests; real corpus: all 20 documents have 10 phrases in rank order with non-increasing scores | ✅ Met |
| AC-08.2 | `test_keyphrases.py` | ✅ Met |
| AC-08.3 | `eval --enrichment` against 5 documents' key terms | ⏳ Awaiting the owner's labels |
| AC-09.1 | 19 of 20 = 0.95 (95% 0.764 to 0.991), at least 4 documents per category, with the active threshold | 🟡 Met at the point estimate only |
| AC-09.2 | The held-out cooking article scores 0.507 against a threshold of 0.649 | ✅ Met |
| AC-09.3 | Tests with `category=Caching`; real corpus with `category=Databases`: 20 of 20 results in each mode from Databases documents | ✅ Met |

## Classification (FR-09)

| | Top-1 cosine, min / median / max |
|---|---|
| 20 public documents | 0.682 / 0.741 / 0.826 |
| 5 calibration fixtures | 0.562 / 0.591 / 0.616 |
| 5 held-out fixtures | 0.505 / 0.528 / 0.657 |

The threshold 0.649099 is the midpoint between the weakest public document (Airflow's DAG-run page, 0.682) and the strongest calibration fixture (the Git guide, 0.616). The groups separate, with a margin of 0.033 and 0 leave-one-out errors. The public documents both calibrate it and are assessed by AC-09.1, so that side is not independent; the held-out fixtures are.

- **The one top-1 error:** Spark's data-sources page, about loading and saving tables, scores Databases 0.701 over Distributed computing 0.685.
- **The held-out miss:** the LaTeX guide scores 0.657 for Databases and is classified. The other three technical off-category fixtures are below the threshold.
- **The rule baseline** maps verified technology entities to categories and may not read user metadata. It gets 11 of 20. Eight documents get no category, because they name their technology only in its ambiguous form (`Spark`, `Airflow`, `Kafka`), which is verified only in context. Airflow's overview gets Databases from its PostgreSQL mentions.

**Finding: secondary categories carry little information.** P9-6 assigns up to 3 categories at or above the threshold. On the public documents the second and third scores run from 0.609 to 0.751, and 35 of those 40 are at or above 0.649. So 16 of 20 documents get all 3 categories and only 1 gets a single one; the PostgreSQL pages get Distributed streaming, for example. No criterion is affected: AC-09.1 judges the top category, and every public document has a user category, which decides filters. Only DDIA uses inferred categories, and its three (Databases 0.798, Distributed streaming 0.768, Distributed computing 0.754) suit that book. A margin rule relative to the top score would fix this, but it amends P9-6, and this corpus cannot calibrate it, because DDIA is the only document without a user category. The decision is the owner's ([decisions](DECISIONS.md#phase-9-completion-2026-11-12)).

## Entities, keyphrases and segmentation on the real corpus

On the 20 public documents, `enrich` stores 5,598 entities, 5,491 of them verified, under 1,073 distinct entity keys. Gazetteer matches give 717 technology, 874 component and 1,405 concept mentions; the patterns give 2,416 identifiers and 79 protocols. The 107 unverified ones are ambiguous names out of context, mostly `worker` and `operator`. They are stored at confidence 0.4 and never filter. The gazetteer is unchanged since sampling (`058dc8a8...`), so the entity set, once labeled, is held out.

Keyphrases with RAKE's default score favor long, rare phrases, such as `widely considered bad style` or `0.029 ms execution time`. rake-nltk also drops any run of more than 4 non-stop words instead of trimming it. Short key terms such as `consumer group` may therefore rank low. That is a measured choice, not a guess: `eval --enrichment` scores all 3 RAKE metrics, with and without code blocks, on the key-term gold set, and reports the best variant beside the configured one (P9-5).

The spaCy policy is built, tested and selectable, and chunking stays on the P0 rules. Its rules were written from the requirement's examples and the guidelines, before any boundary was scored, so the first scoring is a fair comparison. P9-2 adopts it for chunking only if it beats the rules on the gold set and the owner accepts the re-chunk, re-index, `eval` and threshold review that follow.

## Run times

`enrich` takes 17 to 21 s for all 21 documents. The slowest is DDIA, at 4.1 to 4.6 s, about a quarter of the total. With nothing changed, a rerun skips all 21. In the final report, in-memory extraction for the largest public document, Kafka's design page (85,823 characters), takes 80 ms for entities and 72 ms for keyphrases (P9-12). `eval --enrichment` takes 28 to 65 s, mostly classifying the fixtures with the real embedding model.

## Tests

The offline suite passes in four groups, one process each (`python scripts/run_tests.py`):

| Group | Modules | Result | Time |
|---|---|---|---|
| core | schemas, settings, registry, safety, normalization, segmentation, loaders, ingest, online, chunking | 238 passed, 2 skipped | 89 s |
| retrieval | versioning, indexing, cli | 106 passed | 302 s |
| answering | evaluation, generation, citations, sufficiency | 99 passed, 1 skipped | 327 s |
| enrichment | entities, keyphrases, nlp_gold, enrichment, classification, enrichment_eval | 122 passed | 300 s |
| **Total** | 23 modules | **565 passed, 3 skipped, 0 failed** | about 17 min |

The skips are the two opt-in `--live` network tests and the `--live-model` test, as in Phase 8. The spaCy tests ran (spaCy 3.8.18 installed).

Run alone before the Chroma fix, a module's process used up to about 680 MB, growing with the number of cached clients. With the fix, modules that use Chroma end each test with no cached client.

## What remains

For the project owner, in this order:

1. **Label the gold sets** without running `enrich` or looking at the gazetteer: the entity sheet (20 chunks) and the key-term sheet (5 documents) in `data/nlp/`, and review the 66 drafted sentence boundaries. The [guidelines](../datasets/nlp/GUIDELINES.md) say how.
2. **Freeze them:** `python datasets/nlp_gold.py freeze --reviewer NAME`.
3. **Measure:** `techdocqa eval --enrichment --report-dir reports/evaluation`. That settles AC-06.4, AC-07.4 and AC-08.3, and gives the P9-2 decision (does spaCy beat the rules?) and the P9-5 decisions (RAKE metric and code blocks).
4. **Approve or amend** the [completion decisions](DECISIONS.md#phase-9-completion-2026-11-12): the adopted threshold, the similarity-scale guard, keyphrase policy v2 and its metric setting, and the secondary-category finding.
5. If spaCy is adopted: set `segmentation = "spacy"`, then `chunk`, `index`, `enrich` and `eval`, and review the Phase 8 refusal thresholds.
