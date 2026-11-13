# Phase 9 P1 NLP enrichment

Implementation and evidence checkpoint 2026-11-12, completed 2026-11-13, on Windows, Python 3.13.3, local Ollama with `nomic-embed-text:latest`, spaCy 3.8.18 and `rake-nltk` 1.0.6. Phase 9 adds FR-07 entities, FR-08 keyphrases and FR-09 categories through `enrich`, the FR-06 P1 spaCy segmentation policy, and `eval --enrichment`, which measures all of them. It covers the [Phase 9 plan](PHASE_9_PLAN.md) under its [contracts](DECISIONS.md#phase-9-contracts-2026-11-07).

**Result: Phase 9 is complete.** Everything is built and run on the real corpus. Every criterion is measured, and the held-out round 2 has been scored once.

- **Classification.** On the 20 public documents, 19 of 20 land in their manifest category: 0.95 against a target of 0.85, **met at the point estimate only**, because the 95% interval starts at 0.764. The cooking article and 3 other held-out out-of-topic fixtures are `unclassified`; the fifth, a LaTeX guide, is not.
- **Real-corpus checks.** AC-07.2, AC-07.3, AC-08.1 and AC-09.3 pass in both retrieval modes. Unfiltered retrieval is unchanged: the smoke `eval` fingerprint after `enrich` equals the Phase 8 baseline.
- **AC-06.4 is met at the point estimate only:** boundary F1 0.989 for both policies on round 1, after a spaCy line-break bug that the first scoring exposed was fixed.
- **Round 1.** AC-07.4 (precision 0.730, recall 0.491) and AC-08.3 (0 of 72 key terms) were not met, and the owner recorded both as not met on 2026-11-12. Entity rules v2 and the `technical-ngrams-v1` keyphrase policy were then built on round 1, which became development data. They were measured once on a fresh, blind round 2 ([round 2](#round-2-held-out-2026-11-13)).
- **AC-07.4 is now met at the point estimate only:** precision 0.892 (166 of 186, 95% from 0.840) and recall 0.619 (166 of 268, 95% from 0.560), against 0.80 and 0.60. Precision is met outright; recall only at the point estimate.
- **AC-08.3 is not met:** on average 0.239 of the annotated key terms are in the top 10, against 0.50.

AI annotators the owner approved labeled the gold sets: Fable 5.1 for round 1 and Fable 5.2 for round 2. Every gold-set score therefore measures agreement with an AI annotator, not human ground truth.

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
| `enrich` with entity rules v2 and `technical-ngrams-v1` (2026-11-13) | Stored entities and keyphrases recomputed. Smoke `eval` [eval_1ad1444f](../reports/evaluation/eval_1ad1444fc4f64e508d0d9f2e1a651e83.md): fingerprint `48ce89dc...a3af410`, still the Phase 8 baseline. |
| Round 1 as development data | [enrichment_e8b952d0](../reports/evaluation/enrichment_e8b952d01ba84d1f93320478eb5dab0a.md): entities 0.929 / 0.709 and key terms 0.432, both flagged as tuned, so neither is evidence. Real-corpus checks met. |
| Round 2 drawn | `nlp_gold.py --round 2 sheets`, 8 s after the round-2 plan was committed (bf55e14), with the gazetteer and extractor code frozen since 3e48ab8. |
| Round 2 labeled and frozen | Four blind Fable 5.2 sessions; frozen in 2982ac8 before any round-2 score was computed ([review log](../datasets/nlp/review_log.md#round-2-how-the-labels-were-made-2026-11-13)). |
| Round 2 scored, once | [enrichment_5d0f6cdc](../reports/evaluation/enrichment_5d0f6cdcc0bd41ddaa2a05dc5bf0f029.md), not tuned: AC-07.4 met at the point estimate only, AC-08.3 not met. The report says `dirty: True` only because of an untracked `research_notes/` folder; the code is 2982ac8 unchanged. |

## Acceptance

| Criterion | Evidence | Result |
|---|---|---|
| AC-06.1 to AC-06.3 | `test_segmentation.py`, both policies | ✅ Met |
| AC-06.4 | 66 gold sentences, 46 internal boundaries: spaCy v2 and the rules both reach F1 0.989 (precision 45 of 45, recall 45 of 46); F1 from the lower bounds is 0.904 | 🟡 Met at the point estimate only |
| AC-07.1 | `test_entities.py` fixture | ✅ Met |
| AC-07.2 | Tests; real corpus: 5,598 entity rows on the 20 public documents, every chunk ID, document ID and both offsets valid | ✅ Met |
| AC-07.3 | Tests with `entity=Redis`; real corpus with `entity=PostgreSQL`: 20 of 20 results in each mode carry a verified PostgreSQL entity | ✅ Met |
| AC-07.4 | Held-out round 2, 32 labeled chunks, 268 mentions: precision 0.892 (166 of 186, 95% 0.840 to 0.929), recall 0.619 (166 of 268, 95% 0.560 to 0.675). Round 1 before the improvement: 0.730 and 0.491, not met | 🟡 Met at the point estimate only |
| AC-08.1 | Tests; real corpus: all 20 documents have 10 phrases in rank order with non-increasing scores | ✅ Met |
| AC-08.2 | `test_keyphrases.py` | ✅ Met |
| AC-08.3 | Held-out round 2, 15 documents, 216 key terms: mean 0.239 in the configured top 10 (pooled 51 of 216, 95% 0.184 to 0.297). Round 1 before the improvement: 0 of 72 | ❌ Not met |
| AC-09.1 | 19 of 20 = 0.95 (95% 0.764 to 0.991), at least 4 documents per category, with the active threshold | 🟡 Met at the point estimate only |
| AC-09.2 | The held-out cooking article scores 0.507 against a threshold of 0.649 | ✅ Met |
| AC-09.3 | Tests with `category=Caching`; real corpus with `category=Databases`: 20 of 20 results in each mode from Databases documents | ✅ Met |

AC-06.4, AC-07.4 and AC-08.3 are scored against gold sets labeled by an AI annotator, so they measure agreement with it, not human ground truth ([decision](DECISIONS.md#phase-9-completion-2026-11-12)). AC-06.4 stands on round 1, where the segmenter was not tuned. AC-07.4 and AC-08.3 stand on round 2, because the extractor was tuned on round 1. The targets in this table are the requirement's, unchanged.

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

This section is round 1. Round 1 has since been used to develop the AC-07.4 and AC-08.3 improvements, so it is development data, and those criteria are judged on the held-out [round 2](#round-2-held-out-2026-11-13). Report [enrichment_22888006](../reports/evaluation/enrichment_22888006a487494d8005065bae6c36db.md). Fable 5.1, an AI model, labeled the gold sets. The owner approved it as annotator on 2026-11-12, as a deviation from the plan, under which the owner was to label them. **Every figure in this section measures agreement with an AI annotator, not human ground truth.** The figures are also indicative, because the sets are small (VULN-04).

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

The first two causes are conventions, where the gazetteer and the annotator read the guidelines differently. Counted from this report, resolving them would give precision 0.90 (100 of 111) and recall 0.61 (100 of 165). That figure is hypothetical, not a result: changing either side now would tune on this sample. **AC-07.4 is recorded as not met** (owner decision 2026-11-12). Its thresholds are provisional in the requirement (Q-14) but unchanged. Success may be claimed only after the conventions are aligned and the extractor is measured on a fresh blind sample. That measurement is [round 2](#round-2-held-out-2026-11-13).

### Key terms (AC-08.3, P9-5)

None of the 72 key terms is in the configured top 10. The best variants, `word_degree` and `word_frequency`, find 1, and a loose match, where one phrase contains the other, finds 21% to 24%. The cause is structural. RAKE ranks whole runs of content words between stop words, so its top 10 are 3- and 4-word phrases (3.86 words on average with the default metric, 2.92 with `word_frequency`), while 71 of the 72 terms have 1 or 2 words. No RAKE metric or code-block setting closes that gap, so the configured `degree_to_frequency` with code blocks stays. **AC-08.3 is recorded as not met** (owner decision 2026-11-12). Shorter candidates were recorded as a proposed improvement, then built and [measured on round 2](#round-2-held-out-2026-11-13).

## Round 2 (held out, 2026-11-13)

Report [enrichment_5d0f6cdc](../reports/evaluation/enrichment_5d0f6cdcc0bd41ddaa2a05dc5bf0f029.md). Round 2 followed the [plan fixed before sampling](../datasets/nlp/review_log.md#round-2-plan-fixed-before-sampling-2026-11-13):

- It was drawn after the extractor was frozen.
- Four Fable 5.2 sessions labeled it blind.
- It was frozen before any score was computed, then scored once.

Nothing was changed after the score was seen. The owner confirmed Fable 5.2 as annotator on 2026-11-13. It is a different model from round 1's annotator, so the two rounds are not strictly comparable. Every figure below measures agreement with an AI annotator and is indicative (VULN-04).

### Entities (AC-07.4)

32 chunks, 8 per technology, 12 in the ambiguous-name stratum, with 268 labeled mentions.

- Precision 0.892 (166 of 186 verified mentions, 95% 0.840 to 0.929). The lower bound clears 0.80.
- Recall 0.619 (166 of 268, 95% 0.560 to 0.675). Only the point estimate clears 0.60.
- **AC-07.4 is met at the point estimate only.** Ignoring type, precision is 0.925 and recall 0.642.

| Type | Precision | Recall |
|---|---|---|
| TECHNOLOGY | 1.000 (26 of 26) | 0.788 (26 of 33) |
| COMPONENT | 0.913 (21 of 23) | 0.724 (21 of 29) |
| CONCEPT | 0.875 (28 of 32) | 0.301 (28 of 93) |
| PROTOCOL | 1.000 (1 of 1) | 1.000 (1 of 1) |
| IDENTIFIER | 0.865 (90 of 104) | 0.804 (90 of 112) |

Recall by technology: Spark 0.739, Kafka 0.622, Airflow 0.604 and PostgreSQL 0.491. The ambiguous-name stratum recalls as much as the rest (0.618 against 0.621), at lower precision (0.856 against 0.939). On round 1, the same code scored 0.929 and 0.709, on the data it was tuned on.

The 20 false positives and 102 misses have three causes:

| Cause | False positives | Misses |
|---|---|---|
| Same text, different type. The CamelCase rule makes the plan nodes `BitmapAnd`, `BitmapOr` and `MergeAppend` identifiers, and so `TaskGroups` and `JVMs`. The gazetteer makes `TaskFlow API` a component. The annotator made them concepts or technologies. | 6 | 6 |
| Extracted but not labeled: attribute chains on local variables (`self.url`, `exception.response.status_code`), link fragments (`configuration.html#spark-properties`), `URLs`, `NOT` and `EXISTS` split out of `IF NOT EXISTS`. Also gazetteer terms the annotator did not label in that chunk, such as `WAL` beside the labeled `WAL record`. | 14 | 0 |
| No rule finds them. 60 concepts outside the gazetteer: `tasks`, `messages`, `events`, `transaction`, `heartbeat`, `event loop`. 22 identifiers: imported modules such as `httpx` and `datetime`, the commands `psql`, `cd` and `make`, and the single keywords `STRING` and `OPTIONS`. 8 components (`worker`, `triggerer`) and 6 technologies (`Kryo`, `asyncio`, `parquet`, `Twitter chill`). | 0 | 96 |

Precision holds on unseen data. Recall is limited by concepts: the gazetteer finds 28 of the 93 labeled.

### Key terms (AC-08.3)

15 documents, every evaluation document not in round 1, from 13 to 123 chunks, with 216 terms, 13 to 15 per document.

- The configured `ngram/with_code` scores a mean of 0.239 (pooled 51 of 216, 95% 0.184 to 0.297). **AC-08.3 is not met.**
- `ngram/without_code` scores 0.243, one term more. The setting was not changed after the score was seen: the verdict is always the configured variant's. The best RAKE variant scores 0.046, and the former default 0.005.
- Documents of 30 chunks or fewer score 0.272 (7 documents), longer ones 0.210 (8). On round 1's five short documents, the policy was tuned to 0.432.
- The lenient match, where one term contains the other, is a diagnostic only: 0.461.

| Document | Hits | Document | Hits | Document | Hits |
|---|---|---|---|---|---|
| K06 Airflow Dag runs | 6 of 13 | K11 Kafka design | 1 of 15 | K16 PostgreSQL advanced features | 1 of 14 |
| K07 Airflow tasks | 3 of 14 | K12 Spark cluster overview | 5 of 14 | K17 PostgreSQL SQL language | 2 of 15 |
| K08 Airflow Dags | 5 of 15 | K13 Spark submitting applications | 3 of 15 | K18 PostgreSQL isolation | 6 of 15 |
| K09 Kafka quickstart | 5 of 13 | K14 Spark load and save | 3 of 14 | K19 PostgreSQL transaction system | 5 of 15 |
| K10 Kafka producer configs | 0 of 15 | K15 Spark tuning | 2 of 14 | K20 PostgreSQL EXPLAIN | 4 of 15 |

Why 165 terms are missed. This is descriptive only; nothing was changed.

- **Ceiling.** With 13 to 15 terms and 10 slots, even a perfect top 10 would average 0.696.
- **Typed identifiers.** 34 of the misses are configuration keys, flags or function names. K10's 15 terms are mostly producer keys such as `linger.ms`. Its top 10 are words repeated in every row of the configuration table (`valid`, `importance`, `null valid`, `low`, `medium`), so it scores 0.
- **Example data and markup.** These take top-10 places: `san francisco`, `weather`, `city` and `temp_lo` (K17), `cities` and `salary` (K16), `find full` and `spark repo` (K14), and the HTML table tags `td` and `tr` in K12's Markdown.
- **Length and form.** 8 terms have 3 or 4 words, which the policy cannot produce. 5 have the other singular or plural form in the top 10, such as `window function` for `window functions`.

The n-gram policy improves on RAKE on the same held-out set, 0.239 against 0.005, but it reaches less than half the target.

## Entities, keyphrases and segmentation on the real corpus

With entity rules v2 and the 2026-11-12 gazetteer, `enrich` stores 6,386 entities on the 20 public documents, 6,276 of them verified, under 1,130 distinct entity keys. The verified ones are 3,320 identifiers, 1,568 concepts, 717 technologies, 592 components and 79 protocols. 797 come from the new SQL-keyword rule. The 110 unverified ones are ambiguous names out of context, mostly `worker` and `operator`. They are stored at confidence 0.4 and never filter. Under rules v1 the figures were 5,598 entities, 5,491 verified, under 1,073 keys.

The default keyphrases now come from `technical-ngrams-v1`. Its top 10 hold short subject terms (`dag run`, `data interval`, `isolation level`, `wal record`). They also hold words that repeat in tables, example data and markup (see [round 2](#key-terms-ac-083)). RAKE's default score, still selectable, favors long, rare phrases, such as `widely considered bad style` or `0.029 ms execution time`. rake-nltk also drops any run of more than 4 non-stop words instead of trimming it, so short key terms such as `consumer group` rank low. Both gold sets confirm this for all 3 RAKE metrics.

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

After the round-2 freeze and scoring on 2026-11-13, which changed data and documentation but no code, the enrichment group was run once more as a whole: 144 passed in 271 s, now including the tests added after its previous full run. Core, retrieval and answering were not rerun, since no code changed after their last runs.

Run alone before the Chroma fix, a module's process used up to about 680 MB, growing with the number of cached clients. With the fix, modules that use Chroma end each test with no cached client.

## What remains

**Phase 9 is complete.** The owner's decisions of 2026-11-12 ([decisions](DECISIONS.md#phase-9-completion-2026-11-12)) are carried out, and so is the round-2 task:

1. **Annotators.** Fable 5.1 labeled round 1 (approved 2026-11-12) and Fable 5.2 round 2 (confirmed 2026-11-13), both as recorded deviations from the plan. The gold-set scores measure agreement with an AI annotator, not human ground truth.
2. **AC-07.4.** The entity conventions are aligned, and the extractor was measured once on a fresh blind sample: **met at the point estimate only**, with precision 0.892 and recall 0.619 (interval from 0.560).
3. **AC-08.3.** The shorter key-phrase candidates were measured once on a fresh key-term set: **not met**, at a mean of 0.239.

The measurement steps are done. `enrich` was re-run with the new rules and policy, and the smoke fingerprint is unchanged. Round 2 was drawn, labeled blind, frozen and scored once.

Nothing blocks Phase 10. Four points stay open, and none changes a Phase 9 result:

- **AC-07.4 at the point estimate.** It is recorded the way AC-06.4 and AC-09.1 are. Recall's lower bound, 0.560, is below 0.60, and concepts are the weak type (recall 0.301). The requirement calls these thresholds provisional (Q-14); any amendment is the owner's.
- **AC-08.3 not met.** Further keyphrase work would be a new task. Round 2 has now been seen, so it would need another held-out key-term set. Round 2's [misses](#key-terms-ac-083) point to typed identifiers, words from tables and example data, and markup. With 13 to 15 terms and 10 slots, even a perfect top 10 would average 0.696. Appendix C asks for AC-08.3's target to be confirmed (Q-14).
- **Secondary categories (P9-6).** They stay as they are until Phase 10 adds documents without a user category.
- **Hashed lock (P9-11).** Converting the whole `requirements.lock.txt` to a hashed lock is the separate chore planned for after Phase 9.

Both rounds are frozen. `python datasets/nlp_gold.py check` and `python datasets/nlp_gold.py --round 2 check` confirm they still match the corpus. Round 2 is scored, so for any later change to the extractor both rounds are development data.

<a id="improvements-built-awaiting-held-out-measurement"></a>
## Improvements: built and measured on round 2

Both were recorded on 2026-11-12 as proposed improvements and made a separate implementation task the same day. Both were built and tested, then measured once on held-out round 2. Neither changes a criterion.

| Criterion | Proposal | Built | Held-out result (round 2) |
|---|---|---|---|
| AC-07.4 | Align the entity conventions, either in the gazetteer and rules or in the guidelines: the type of named Airflow, Spark and PostgreSQL terms, and a path versus a file name | [Entity rules v2](DECISIONS.md#entity-rules-v2): types aligned with the guidelines' table, file names from paths, upper-case SQL keywords. The guidelines now write down the round-1 annotators' conventions. | 32 chunks: precision 0.892, recall 0.619. Met at the point estimate only (round 1 before: 0.730 and 0.491) |
| AC-08.3 | Shorter keyphrase candidates, such as n-grams of up to 2 or 3 words or noun phrases; amends P9-5 | [technical-ngrams-v1](DECISIONS.md#technical-ngrams-v1), the new default, with RAKE still selectable | 15 documents: mean 0.239. Not met (round 1 before: 0.000 with RAKE) |

The changes were made while looking at round 1's labels, so `eval --enrichment` reports any new score on round 1 as tuned. Such a score is never evidence for acceptance. Research behind the n-gram policy: [Short technical keyphrase extraction](../reports/Short%20technical%20keyphrase%20extraction.md). One finding there bounds what to expect. With 14 or 15 gold terms per document, even a perfect top 10 holds at most about 70% of them, so a mean of 0.50 needs about 7 of the top 10 to be gold terms. Round 2 gets 3.4 on average.
