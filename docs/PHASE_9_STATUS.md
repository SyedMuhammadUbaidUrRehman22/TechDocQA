# Phase 9 P1 NLP enrichment

Implementation and evidence checkpoint 2026-11-12 on Windows, Python 3.13.3, local Ollama with `nomic-embed-text:latest`, spaCy 3.8.18 and `rake-nltk` 1.0.6. Phase 9 adds FR-07 entities, FR-08 keyphrases and FR-09 categories through `enrich`, the FR-06 P1 spaCy segmentation policy, and `eval --enrichment`, which measures all of them. It covers the [Phase 9 plan](PHASE_9_PLAN.md) under its [contracts](DECISIONS.md#phase-9-contracts-2026-11-07).

**Result:** everything is built, run on the real corpus and measured. On the 20 public documents, classification puts 19 of 20 in their manifest category: 0.95 against a target of 0.85, **met at the point estimate only**, because the 95% interval starts at 0.764. The cooking article and 3 other held-out out-of-topic fixtures are `unclassified`; the fifth, a LaTeX guide, is not. The real-corpus checks for AC-07.2, AC-07.3, AC-08.1 and AC-09.3 pass in both retrieval modes. Unfiltered retrieval is unchanged: the smoke `eval` fingerprint before and after `enrich` equals the Phase 8 baseline. The gold sets were labeled by Fable 5.1, an AI model the owner approved as annotator, and frozen on 2026-11-12. Their scores therefore measure agreement with an AI annotator, not human ground truth ([gold-set results](#gold-set-results)). **AC-06.4 is met at the point estimate only:** boundary F1 0.989 for both policies, after a spaCy line-break bug that the first scoring exposed was fixed. **AC-07.4 is not met** (precision 0.730 and recall 0.491, against 0.80 and 0.60), and **neither is AC-08.3** (0 of 72 key terms in the top 10). The owner recorded both as not met on 2026-11-12, then approved the threshold, the similarity-scale guard and keyphrase policy v2, kept the P9-6 rule for secondary categories, and made the two improvements a separate implementation task. Both improvements are now built and tested, but not yet measured on held-out data, so both criteria stay not met ([improvements](#improvements-built-awaiting-held-out-measurement)).

## What was added

The storage, commands and extractors were committed earlier (60458fc); this checkpoint adds the measurement, the threshold, the segmenter and the fixes listed under [Fixes](#fixes-found-while-completing-the-phase).

| Area | Behavior | Code |
|---|---|---|
| Storage and commands | Registry schema v3 with a verified pre-upgrade backup. `enrich [version_ids]` writes entities, keyphrases and categories in one transaction per document and skips unchanged ones. `enrichment DOC [--chunk-id]` shows them, read-only. | [registry.py](../src/techdocqa/registry.py), [pipeline.py](../src/techdocqa/enrichment/pipeline.py) |
| Entities (FR-07) | The [gazetteer](../config/gazetteer.toml) plus regex rules for identifiers and protocols. Ambiguous names count as exact only in context. Only verified entities feed `--entity` in both modes. Rules v2 and the 2026-11-12 gazetteer align types with the guidelines, take a file name from a path and add upper-case SQL keywords ([decision](DECISIONS.md#entity-rules-v2)). | [entities.py](../src/techdocqa/enrichment/entities.py) |
| Keyphrases (FR-08) | Top 10 per document. The default since 2026-11-12 is `technical-ngrams-v1`, which ranks 1- and 2-word terms ([decision](DECISIONS.md#technical-ngrams-v1)). RAKE stays selectable: policy `rake-nltk-technical-v2` keeps contractions and possessives whole and drops Markdown emphasis underscores, and `keyphrase_metric` chooses its word score. | [keyphrases.py](../src/techdocqa/enrichment/keyphrases.py) |
| Categories (FR-09) | Cosine between a document's mean chunk vector and each category description. The new `unclassified` threshold applies only while `similarity_config_id` names the active scale (policy, embedding profile and descriptions), as Phase 8 thresholds do. A stale threshold classifies nothing and warns `CLASSIFICATION_CALIBRATION_STALE`. | [classification.py](../src/techdocqa/enrichment/classification.py), [settings.py](../src/techdocqa/settings.py) |
| Segmentation (FR-06 P1) | `[chunking] segmentation = "spacy"` selects `spacy-technical-sentences-v2`: spaCy's tokenizer and rule-based sentencizer, then technical rules (below). The default, `"rules"`, keeps every existing chunking configuration ID. | [segmentation.py](../src/techdocqa/segmentation.py), [chunking.py](../src/techdocqa/chunking.py) |
| Measurement | `eval --enrichment` scores the gold sets, classifies the out-of-topic fixtures in memory, proposes the `unclassified` threshold and checks the enriched corpus. It writes nothing to the registry, index or configuration. `--gold-dir datasets/nlp/round2 --fixtures datasets/nlp/out_of_topic.jsonl` scores round 2; a score on a set the code was tuned on is flagged as tuned. | [enrichment.py](../src/techdocqa/evaluation/enrichment.py), [cli.py](../src/techdocqa/cli.py) |
| Gold-set tool | `nlp_gold.py --round 2` draws the held-out round 2: a new seed, 32 entity chunks kept apart from round 1 and all 15 unused key-term documents ([decision](DECISIONS.md#round-2-gold-sets)). | [nlp_gold.py](../datasets/nlp_gold.py) |
| Fixtures | 10 out-of-topic texts written for this phase, 5 to calibrate and 5 held out, the cooking article among the held out. Six are non-technical and four are technical but off-category (CSS, Git, home Wi-Fi, LaTeX), so the threshold is not judged only on easy cases. | [out_of_topic.jsonl](../datasets/nlp/out_of_topic.jsonl) |
| Tests | `scripts/run_tests.py` runs the suite in four groups, one process each. An autouse fixture releases Chroma's cached clients after each test. | [run_tests.py](../scripts/run_tests.py), [conftest.py](../tests/conftest.py) |

### The spaCy policy's technical rules

The sentencizer proposes boundaries after `.`, `!` and `?`. The policy then applies five rules, each from the requirement's examples or the annotation guidelines, and none tuned on the gold sheet:

1. A blank line is a boundary, and so is a line that starts with a list marker. A single line break is not, because PDF and Markdown text is hard-wrapped.
2. A boundary needs whitespace before it, so `System.Console` and `end.Next` never split.
3. No boundary after abbreviations such as `e.g.`, `Fig.`, `vs.` or `Dr.`. `etc.` ends a sentence only before an uppercase word.
4. An opening quote or bracket left at the end of a sentence moves to the next one.
5. No boundary inside protected code.

Version 2 also moves a proposed start that falls on a line-break token to the next word, which fixes a defect rather than adding a rule ([fixes](#fixes-found-while-completing-the-phase)).

Spans keep the P0 contract: half-open offsets that cover every character, so AC-06.1 to AC-06.3 hold for both policies.

## Fixes found while completing the phase

- **Registry migration hang (P9-8).** The v2 to v3 migration took its backup with SQLite's backup API from the connection that held `BEGIN IMMEDIATE`. SQLite returns `SQLITE_BUSY` to a backup whose source connection is in a write transaction, and Python's `backup()` retries that forever. So the first open of any v1 or v2 registry hung, including the real one, and so did three migration tests. The backup now reads through a second, read-only connection. The migrating connection still holds the write lock from before the copy until the commit but has written nothing yet, so the copy is exactly the state being migrated and nothing can commit in between. The reader is closed before the commit.
- **Two test bugs hidden by the hang.** A race test compared `sqlite3.Row` objects with tuples. The entity-filter test in `test_indexing.py` relied on a relative gazetteer path, so it failed when run on its own.
- **spaCy boundaries at line breaks (P9-2).** When a sentence ends at a single line break, spaCy's sentencizer starts the next sentence at the newline token. Rule 2 then looked at the token before it, the period, found no whitespace after it and dropped the boundary. So v1 never split at a line break: on the gold set it found 33 of 46 boundaries (F1 0.835, report [enrichment_58c67164](../reports/evaluation/enrichment_58c67164e8e84b708c80e6df4721518f.md)). v2 starts the sentence at the next word, and a regression test covers the case. The first scoring found the bug, so the v2 figure is not blind, but no rule was changed or added.
- **Gold file line endings.** `freeze` wrote the gold files with CRLF on Windows and logged the hashes of those bytes, which a checkout with LF would not reproduce. It now writes LF, and so does the enrichment report writer.
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
| Gold sets frozen | Labeled by Fable 5.1, the owner-approved AI annotator, checked and frozen; `nlp_gold.py check` passes ([review log](../datasets/nlp/review_log.md)). |
| `eval --enrichment` on the gold sets | [enrichment_58c67164](../reports/evaluation/enrichment_58c67164e8e84b708c80e6df4721518f.md), the blind run: spaCy v1 boundary F1 0.835. |
| After the spaCy fix | [enrichment_22888006](../reports/evaluation/enrichment_22888006a487494d8005065bae6c36db.md): spaCy v2 boundary F1 0.989; every other figure unchanged. |

## Acceptance

| Criterion | Evidence | Result |
|---|---|---|
| AC-06.1 to AC-06.3 | `test_segmentation.py`, both policies | ✅ Met |
| AC-06.4 | 66 gold sentences, 46 internal boundaries: spaCy v2 and the rules both reach F1 0.989 (precision 45 of 45, recall 45 of 46); F1 from the lower bounds is 0.904 | 🟡 Met at the point estimate only |
| AC-07.1 | `test_entities.py` fixture | ✅ Met |
| AC-07.2 | Tests; real corpus: 5,598 entity rows on the 20 public documents, every chunk ID, document ID and both offsets valid | ✅ Met |
| AC-07.3 | Tests with `entity=Redis`; real corpus with `entity=PostgreSQL`: 20 of 20 results in each mode carry a verified PostgreSQL entity | ✅ Met |
| AC-07.4 | 20 labeled chunks, 165 mentions: precision 0.730 (81 of 111), recall 0.491 (81 of 165) | ❌ Not met (owner decision 2026-11-12) |
| AC-08.1 | Tests; real corpus: all 20 documents have 10 phrases in rank order with non-increasing scores | ✅ Met |
| AC-08.2 | `test_keyphrases.py` | ✅ Met |
| AC-08.3 | 5 documents, 72 key terms: 0 in the configured top 10, at most 1 with any other variant | ❌ Not met (owner decision 2026-11-12) |
| AC-09.1 | 19 of 20 = 0.95 (95% 0.764 to 0.991), at least 4 documents per category, with the active threshold | 🟡 Met at the point estimate only |
| AC-09.2 | The held-out cooking article scores 0.507 against a threshold of 0.649 | ✅ Met |
| AC-09.3 | Tests with `category=Caching`; real corpus with `category=Databases`: 20 of 20 results in each mode from Databases documents | ✅ Met |

AC-06.4, AC-07.4 and AC-08.3 are scored against gold sets labeled by an AI annotator, so they measure agreement with it, not human ground truth ([decision](DECISIONS.md#phase-9-completion-2026-11-12)). The targets in this table are the requirement's, unchanged.

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

## Gold-set results

Report [enrichment_22888006](../reports/evaluation/enrichment_22888006a487494d8005065bae6c36db.md). Fable 5.1, an AI model, labeled the gold sets. The owner approved it as annotator on 2026-11-12, as a deviation from the plan, under which the owner was to label them. **Every figure in this section measures agreement with an AI annotator, not human ground truth.** The figures are also indicative, because the sets are small (VULN-04).

### Sentences (AC-06.4, P9-2)

Both policies place 45 of the 46 internal boundaries and add none: F1 0.989, with 64 of 66 sentences exact. The one miss, shared, is in S15's flattened list, where an item without end punctuation is followed by `local:`. The verdict is "met at the point estimate only" because F1 from the interval lower bounds is 0.904. spaCy does not beat the rules, so under P9-2 chunking stays on the rules and nothing is re-chunked.

### Entities (AC-07.4)

Precision is 0.730 (81 of 111 verified mentions, 95% 0.640 to 0.804) and recall 0.491 (81 of 165, 95% 0.416 to 0.567). The gazetteer is unchanged since sampling, so the figure is held out. Ignoring type, precision is 0.838 and recall 0.567. The 30 false positives and 84 misses have four causes:

| Cause | False positives | Misses |
|---|---|---|
| Same text, different type. The gazetteer makes Operators, Sensors, XComs, RDDs, GIN, GiST and SP-GiST components, and `spark-submit`, `SparkConf` and `EXPLAIN` too; the annotator made them concepts or identifiers. | 12 | 12 |
| Path or file name. The identifier rule takes `bin/kafka-topics.sh` and `examples/src/main/python/pi.py`; the annotator labeled the file names. | 7 | 7 |
| No rule finds them: 19 SQL keywords such as `SELECT` and `ORDER BY`, concepts outside the gazetteer such as `task`, `transaction` and `startup cost`, lowercase code names such as `mytab`, and Go, JVM, YARN and Parquet. | 0 | 65 |
| Extracted but not labeled: `IoT` twice, Airflow's `sensor` in Kafka's text twice, `Dag runs`, `QUERY PLAN`, `deploy mode`, two method chains, `TaskFlow-decorated` and `operators`. | 11 | 0 |

The first two causes are conventions, where the gazetteer and the annotator read the guidelines differently. Counted from this report, resolving them would give precision 0.90 (100 of 111) and recall 0.61 (100 of 165). That figure is hypothetical, not a result: changing either side now would tune on this sample. **AC-07.4 is recorded as not met** (owner decision 2026-11-12). Its thresholds are provisional in the requirement (Q-14) but unchanged. Success may be claimed only after the conventions are aligned and the extractor is measured on a fresh blind sample.

### Key terms (AC-08.3, P9-5)

None of the 72 key terms is in the configured top 10. The best variants, `word_degree` and `word_frequency`, find 1, and a loose match, where one phrase contains the other, finds 21% to 24%. The cause is structural. RAKE ranks whole runs of content words between stop words, so its top 10 are 3- and 4-word phrases (3.86 words on average with the default metric, 2.92 with `word_frequency`), while 71 of the 72 terms have 1 or 2 words. No RAKE metric or code-block setting closes that gap, so the configured `degree_to_frequency` with code blocks stays. **AC-08.3 is recorded as not met** (owner decision 2026-11-12). Shorter candidates were recorded as a proposed improvement and are now [built](#improvements-built-awaiting-held-out-measurement).

## Entities, keyphrases and segmentation on the real corpus

On the 20 public documents, `enrich` stores 5,598 entities, 5,491 of them verified, under 1,073 distinct entity keys. Gazetteer matches give 717 technology, 874 component and 1,405 concept mentions; the patterns give 2,416 identifiers and 79 protocols. The 107 unverified ones are ambiguous names out of context, mostly `worker` and `operator`. They are stored at confidence 0.4 and never filter. The gazetteer is unchanged since sampling (`058dc8a8...`), so the entity set, once labeled, is held out.

Keyphrases with RAKE's default score favor long, rare phrases, such as `widely considered bad style` or `0.029 ms execution time`. rake-nltk also drops any run of more than 4 non-stop words instead of trimming it. Short key terms such as `consumer group` therefore rank low, as the [key-term gold set](#key-terms-ac-083-p9-5) confirms for all 3 RAKE metrics, with and without code blocks.

The spaCy policy is built, tested and selectable. Its rules were written from the requirement's examples and the guidelines, before any boundary was scored. It ties the rules on the [sentence gold set](#sentences-ac-064-p9-2), so under P9-2 chunking stays on the P0 rules, and no re-chunk, re-index or threshold review is needed.

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

After the gold-set fixes (spaCy policy v2 with its regression test, and LF output from `freeze` and the report writer), the two groups that cover the changed code were rerun: core 238 passed, 2 skipped; enrichment 122 passed. Retrieval and answering do not reach the changed code paths.

After the improvements (entity rules v2, the gazetteer revision, `technical-ngrams-v1`, round-2 sampling and the evaluator's `--fixtures` and tuned flag), on 2026-11-13: core 238 passed, 2 skipped; retrieval 106 passed; enrichment 141 passed. The enrichment group ran before the last evaluator and round-2 changes, so its affected modules were rerun alone afterwards and passed: `test_enrichment_eval.py`, `test_keyphrases.py` and `test_nlp_gold.py`. Answering was not rerun; it does not reach the changed code.

Run alone before the Chroma fix, a module's process used up to about 680 MB, growing with the number of cached clients. With the fix, modules that use Chroma end each test with no cached client.

## What remains

The owner decided three points on 2026-11-12 ([decisions](DECISIONS.md#phase-9-completion-2026-11-12)):

1. Fable 5.1 is approved as the gold-set annotator, as a recorded deviation from the plan. The gold-set scores measure agreement with an AI annotator, not human ground truth.
2. AC-07.4 is recorded as not met. The provisional thresholds are unchanged, and success requires aligned conventions and a fresh blind sample, never tuning and validating on the same sample.
3. AC-08.3 is recorded as not met. Shorter key-phrase candidates are a proposed improvement that needs a fresh key-term set before acceptance.

Later on 2026-11-12 the owner approved the adopted threshold (0.649099), the similarity-scale guard and keyphrase policy v2, kept the P9-6 rule for secondary categories until Phase 10, and made the two improvements a separate implementation task.

That task is built and tested ([below](#improvements-built-awaiting-held-out-measurement)). What remains is its measurement, in this order:

1. Re-run `enrich`, so the stored entities and keyphrases use the new rules and policy, and confirm the corpus checks and the smoke fingerprint.
2. Draw round 2 with `nlp_gold.py --round 2 sheets`, have Fable 5.1 label it blind, check and freeze it.
3. Score it once with `eval --enrichment --gold-dir datasets/nlp/round2 --fixtures datasets/nlp/out_of_topic.jsonl`, and record the result as measured.

The round-1 gold sets need nothing more: they are frozen, and `python datasets/nlp_gold.py check` confirms they still match the corpus. They are now development data.

## Improvements: built, awaiting held-out measurement

Both were recorded on 2026-11-12 as proposed improvements and made a separate implementation task the same day. Both are now built and tested; neither is measured on held-out data yet. Neither changes a criterion, and the results above stand as measured.

| Criterion | Proposal | Built | Required before acceptance |
|---|---|---|---|
| AC-07.4 | Align the entity conventions, either in the gazetteer and rules or in the guidelines: the type of named Airflow, Spark and PostgreSQL terms, and a path versus a file name | [Entity rules v2](DECISIONS.md#entity-rules-v2): types aligned with the guidelines' table, file names from paths, upper-case SQL keywords. The guidelines now write down the round-1 annotators' conventions. | Measurement on a fresh blind entity sample, never on the sample used to tune: round 2, 32 chunks, not yet drawn |
| AC-08.3 | Shorter keyphrase candidates, such as n-grams of up to 2 or 3 words or noun phrases; amends P9-5 | [technical-ngrams-v1](DECISIONS.md#technical-ngrams-v1), the new default, with RAKE still selectable | Measurement against a fresh set of key terms: round 2, all 15 unused documents, not yet drawn |

Round 1 is now development data. The changes were made while looking at its labels, so `eval --enrichment` reports any new score on it as tuned, and such a score is never evidence for acceptance. Research behind the n-gram policy: [Short technical keyphrase extraction](../reports/Short%20technical%20keyphrase%20extraction.md). One finding there bounds what to expect: with 14 or 15 gold terms per document, even a perfect top 10 holds at most about 70% of them, so a mean of 0.50 needs about 7 of the top 10 to be gold terms.
