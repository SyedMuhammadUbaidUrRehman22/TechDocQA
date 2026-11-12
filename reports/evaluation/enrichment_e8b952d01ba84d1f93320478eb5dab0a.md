# Enrichment evaluation enrichment_e8b952d01ba84d1f93320478eb5dab0a

- Date: 2026-11-12T19:20:24.840202+00:00, 26.418 s
- Corpus: `techdocqa-reference-2026-10-24-v2`, 20 of 20 documents, fingerprint `e8713f0c15eeb6db2c801a319c2324507302242c6265b8fff1ae67db63a2c4b5`
- Code: 3e48ab8be6e9b5385abb66ce75ca0ad2a4eac9e0 (dirty: True); enrichment configuration `en_b5e90c2bc4857fc2ec5251e9450f23f10db847317083c3d3978692e45feeb925`
- Gazetteer SHA-256 `7aa9d0f725d871e49a129539ee85a72f9f50c5a69f4d5f697b764de0c52e8744`; category descriptions SHA-256 `67d706a84744b9cde5acad6f5e5623e136d8bcca09fd3d9477383169591a2f00`
- Gold data: segmentation frozen (`fd4aaf641fdd`, 20 rows); entities frozen (`b82e2f094e1a`, 20 rows); keyphrases frozen (`320534b487f0`, 5 rows)
- Out-of-topic fixtures: `datasets/nlp/out_of_topic.jsonl` SHA-256 `e8180839ea52c2af552172ca773049f778f02b18f00fc2ad2e4a2b280b91a71f`

## Acceptance

| Criterion | Target | Result | Verdict |
|---|---|---|---|
| AC-06.4 | boundary F1 >= 0.95 on >= 50 sentences (spaCy policy) | 0.989 | met at point estimate only |
| AC-07.4 | precision >= 0.80, recall >= 0.60 on >= 20 chunks | 0.929 / 0.709 | met on tuned data |
| AC-08.3 | mean share of key terms in the top 10 >= 0.50 over 5 documents | 0.432 | not met on tuned data |
| AC-09.1 | accuracy >= 0.85, >= 2 documents per category | 0.950 | met at point estimate only |
| AC-09.2 | the out-of-topic cooking article is unclassified (result: held-out fixtures unclassified) | 0.800 | met |
| AC-07.2 (real corpus) | see the corpus checks | n/a | met |
| AC-07.3 (real corpus) | see the corpus checks | n/a | met |
| AC-08.1 (real corpus) | see the corpus checks | n/a | met |
| AC-09.3 (real corpus) | see the corpus checks | n/a | met |

## Sentence boundaries (AC-06.4, P9-2)

Boundary F1 over the boundaries between sentences inside each paragraph: a sentence end and the next sentence's start, compared at exact positions after trimming whitespace. Paragraph edges are fixed by the fixture, so they are not counted.

| Policy | Boundary F1 | F1 from lower bounds | Precision | Recall | Exact sentences | Verdict |
|---|---|---|---|---|---|---|
| rules (`technical-sentences-v4`) | 0.989 | 0.904 | 1.000 (45 of 45, 95% 0.921-1.000) | 0.978 (45 of 46, 95% 0.887-0.996) | 0.970 (64 of 66, 95% 0.896-0.992) | met at point estimate only |
| spacy (`spacy-technical-sentences-v2`) | 0.989 | 0.904 | 1.000 (45 of 45, 95% 0.921-1.000) | 0.978 (45 of 46, 95% 0.887-0.996) | 0.970 (64 of 66, 95% 0.896-0.992) | met at point estimate only |

spaCy beats the rules: no. Flagged passages: none.

Errors, rules:

- S15 missed at 231: `from the URI as expected|local: - a URI starting`

Errors, spacy:

- S15 missed at 231: `from the URI as expected|local: - a URI starting`


## Entities (AC-07.4)

Verified mentions (confidence >= 0.5) against the labels, on (chunk, normalized text, type), micro-averaged over 20 chunks. Tuned: yes.

- Precision 0.929 (117 of 126, 95% 0.870-0.962)
- Recall 0.709 (117 of 165, 95% 0.636-0.773)
- F1 0.804

| Type | Precision | Recall |
|---|---|---|
| TECHNOLOGY | 1.000 (17 of 17, 95% 0.816-1.000) | 0.773 (17 of 22, 95% 0.566-0.899) |
| COMPONENT | 1.000 (6 of 6, 95% 0.610-1.000) | 0.667 (6 of 9, 95% 0.354-0.879) |
| CONCEPT | 0.871 (27 of 31, 95% 0.712-0.949) | 0.500 (27 of 54, 95% 0.371-0.629) |
| PROTOCOL | n/a | 0.000 (0 of 1, 95% 0.000-0.793) |
| IDENTIFIER | 0.931 (67 of 72, 95% 0.848-0.970) | 0.848 (67 of 79, 95% 0.753-0.911) |

| Rule family | Precision |
|---|---|
| gazetteer | 0.931 (54 of 58, 95% 0.836-0.973) |
| pattern | 0.926 (63 of 68, 95% 0.839-0.968) |

| Technology | Gold | Predicted | Matched | Precision | Recall |
|---|---|---|---|---|---|
| Apache Airflow | 49 | 37 | 32 | 0.865 | 0.653 |
| Apache Kafka | 19 | 16 | 14 | 0.875 | 0.737 |
| Apache Spark | 56 | 50 | 49 | 0.980 | 0.875 |
| PostgreSQL | 41 | 23 | 22 | 0.957 | 0.537 |

| Format | Gold | Predicted | Matched | Precision | Recall |
|---|---|---|---|---|---|
| html | 147 | 115 | 106 | 0.922 | 0.721 |
| md | 13 | 9 | 9 | 1.000 | 0.692 |
| pdf | 5 | 2 | 2 | 1.000 | 0.400 |

| Ambiguous-name stratum | Gold | Predicted | Matched | Precision | Recall |
|---|---|---|---|---|---|
| False | 92 | 60 | 55 | 0.917 | 0.598 |
| True | 73 | 66 | 62 | 0.939 | 0.849 |

Diagnostics: ignoring type, precision 0.929 and recall 0.713; including unverified mentions, precision 0.902 and recall 0.721.

Errors:

- E01: false positives Dag runs (CONCEPT, gazetteer), TaskFlow-decorated (IDENTIFIER, identifier-camel); missed @task (IDENTIFIER), task (CONCEPT), taskflow (COMPONENT), tasks (CONCEPT)
- E02: false positives first_task.set_downstream (IDENTIFIER, identifier), operators (CONCEPT, gazetteer), third_task.set_upstream (IDENTIFIER, identifier); missed task (CONCEPT), tasks (CONCEPT)
- E03: false positives none; missed go (TECHNOLOGY), jvm (TECHNOLOGY), task (CONCEPT), tasks (CONCEPT), worker (COMPONENT), workers (COMPONENT)
- E04: false positives none; missed cron expression (CONCEPT), tasks (CONCEPT), timedelta (IDENTIFIER), timetables (CONCEPT)
- E05: false positives none; missed tasks (CONCEPT)
- E06: false positives IoT (IDENTIFIER, identifier-camel); missed event streaming (CONCEPT)
- E07: false positives none; missed oauthbearer (PROTOCOL)
- E08: false positives IoT (IDENTIFIER, identifier-camel); missed event streaming (CONCEPT)
- E09: false positives none; missed read-ahead (CONCEPT)
- E10: false positives none; missed send() (IDENTIFIER)
- E12: false positives none; missed parquet (TECHNOLOGY), write (IDENTIFIER)
- E13: false positives none; missed data locality (CONCEPT)
- E14: false positives none; missed join (IDENTIFIER), jvm (TECHNOLOGY), reduce tasks (CONCEPT)
- E15: false positives deploy mode (CONCEPT, gazetteer); missed yarn (TECHNOLOGY)
- E16: false positives none; missed mytab (IDENTIFIER), transaction (CONCEPT), transactions (CONCEPT)
- E17: false positives QUERY PLAN (CONCEPT, gazetteer); missed incremental sort (CONCEPT), sort (CONCEPT), tenk1 (IDENTIFIER), unique1 (IDENTIFIER)
- E18: false positives none; missed limit (CONCEPT), limit (IDENTIFIER), startup cost (CONCEPT), total cost (CONCEPT)
- E19: false positives none; missed gin index (CONCEPT), gin indexes (CONCEPT), gin operator class (CONCEPT), inverted index (CONCEPT), inverted indexes (CONCEPT)
- E20: false positives none; missed createdb (IDENTIFIER), pguser (IDENTIFIER), postgres (IDENTIFIER)

## Key terms (AC-08.3, P9-5)

Configured variant `ngram/with_code` (n-gram policy or RAKE metric / code blocks); the best on this gold set is `ngram/with_code`. N-gram policy tuned on this set: yes.

| Variant | Mean hit rate | Pooled terms | Mean lenient hit rate (diagnostic) | By size (mean hit rate, documents) |
|---|---|---|---|---|
| ngram/with_code | 0.432 | 0.431 (31 of 72, 95% 0.323-0.546) | 0.613 | 30 chunks or fewer: 0.432 (5) |
| ngram/without_code | 0.432 | 0.431 (31 of 72, 95% 0.323-0.546) | 0.613 | 30 chunks or fewer: 0.432 (5) |
| degree_to_frequency/with_code | 0.000 | 0.000 (0 of 72, 95% 0.000-0.051) | 0.210 | 30 chunks or fewer: 0.000 (5) |
| degree_to_frequency/without_code | 0.000 | 0.000 (0 of 72, 95% 0.000-0.051) | 0.210 | 30 chunks or fewer: 0.000 (5) |
| word_degree/with_code | 0.013 | 0.014 (1 of 72, 95% 0.003-0.075) | 0.209 | 30 chunks or fewer: 0.013 (5) |
| word_degree/without_code | 0.013 | 0.014 (1 of 72, 95% 0.003-0.075) | 0.223 | 30 chunks or fewer: 0.013 (5) |
| word_frequency/with_code | 0.013 | 0.014 (1 of 72, 95% 0.003-0.075) | 0.237 | 30 chunks or fewer: 0.013 (5) |
| word_frequency/without_code | 0.013 | 0.014 (1 of 72, 95% 0.003-0.075) | 0.237 | 30 chunks or fewer: 0.013 (5) |

ngram/with_code:

| Document | Technology | Format | Chunks | Hits | Missed | Top 10 |
|---|---|---|---|---|---|---|
| K1 | Apache Airflow | html | 21 | 8 of 15 | executor, api server, triggerer, sensors, xcoms, plugins, dag author | dag, tasks, scheduler, worker, task instance, dag bundle, run, operators, dag processor, metadata database |
| K2 | Apache Kafka | html | 18 | 9 of 14 | kafka cluster, replication factor, producer api, consumer api, clients | topic, events, producers, partition, event streaming, streams, brokers, consumers, kafka connect, kafka streams |
| K3 | Apache Spark | md | 9 | 5 of 14 | hardware provisioning, cpu cores, network, standalone mode, spark.local.dir, java vm, hadoop yarn, noatime, raid | hadoop, hdfs, memory, executors, application, storage system, cluster manager, local disks, nodes, java |
| K4 | PostgreSQL | html | 15 | 6 of 14 | index types, hash index, create index, query planner, inverted indexes, nearest-neighbor, indexing strategies, block range indexes | operator, gist, index, sp-gist, operator classes, b-tree, gin, brin, b-tree index, standard distribution |
| K5 | PostgreSQL | pdf | 18 | 3 of 15 | createdb, dropdb, client/server model, server process, database server, superuser, environment variable, pghost, client applications, sql commands, getting started, installation | database, user account, operating system, name, postgresql user, server, user name, psql, site administrator, create |

## Classification (AC-09.1, AC-09.2, P9-6)

Policy `centroid-cosine-v1`, similarity scale `cs_f138c575d3b18c6553bf96f57e55f743f6637eb359e7d24fbbd95b63451e3803`. Active threshold: calibrated (0.649099 from `enrichment_eaf9c6a675d647008a9a99a0944b1bab`).

- Top-1 accuracy 0.950 (19 of 20, 95% 0.764-0.991)
- Accuracy with the active threshold 0.649 (below it counts as wrong) 0.950 (19 of 20, 95% 0.764-0.991)
- Rule baseline (technology entities mapped to categories, no user metadata) 0.550 (11 of 20, 95% 0.342-0.742)
- Categories assigned per document at that threshold: 0: 0, 1: 1, 2: 3, 3: 16

Confusion matrix (rows: manifest label, columns: top-1):

| Label | Databases | Distributed computing | Distributed streaming | Workflow orchestration |
|---|---|---|---|---|
| Databases (7) | 7 | 0 | 0 | 0 |
| Distributed computing (5) | 1 | 4 | 0 | 0 |
| Distributed streaming (4) | 0 | 0 | 4 | 0 |
| Workflow orchestration (4) | 0 | 0 | 0 | 4 |

| Document | Format | Label | Top categories (cosine) | Rule baseline | Assigned (proposal) |
|---|---|---|---|---|---|
| postgresql-18-transaction-system.txt | txt | Databases | Databases 0.716, Distributed streaming 0.714, Distributed computing 0.674 | Databases | Databases, Distributed streaming, Distributed computing |
| postgresql-18-tutorial-advanced-features.pdf | pdf | Databases | Databases 0.782, Distributed streaming 0.721, Distributed computing 0.678 | Databases | Databases, Distributed streaming, Distributed computing |
| postgresql-18-tutorial-getting-started.pdf | pdf | Databases | Databases 0.755, Distributed streaming 0.637, Distributed computing 0.609 | Databases | Databases |
| postgresql-18-tutorial-sql-language.pdf | pdf | Databases | Databases 0.743, Distributed streaming 0.658, Distributed computing 0.632 | Databases | Databases, Distributed streaming |
| spark-4.0.1-cluster-overview.md | md | Distributed computing | Distributed computing 0.799, Databases 0.687, Distributed streaming 0.686 | unclassified | Distributed computing, Databases, Distributed streaming |
| spark-4.0.1-hardware-provisioning.md | md | Distributed computing | Distributed computing 0.743, Distributed streaming 0.675, Databases 0.667 | unclassified | Distributed computing, Distributed streaming, Databases |
| spark-4.0.1-tuning.md | md | Distributed computing | Distributed computing 0.753, Databases 0.714, Distributed streaming 0.706 | unclassified | Distributed computing, Databases, Distributed streaming |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html | html | Workflow orchestration | Workflow orchestration 0.682, Distributed streaming 0.677, Distributed computing 0.658 | unclassified | Workflow orchestration, Distributed streaming, Distributed computing |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html | html | Workflow orchestration | Workflow orchestration 0.708, Distributed computing 0.681, Distributed streaming 0.679 | unclassified | Workflow orchestration, Distributed computing, Distributed streaming |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html | html | Workflow orchestration | Workflow orchestration 0.755, Distributed computing 0.737, Distributed streaming 0.706 | Databases | Workflow orchestration, Distributed computing, Distributed streaming |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/tasks.html | html | Workflow orchestration | Workflow orchestration 0.739, Distributed streaming 0.700, Distributed computing 0.689 | unclassified | Workflow orchestration, Distributed streaming, Distributed computing |
| https://kafka.apache.org/43/configuration/producer-configs/ | html | Distributed streaming | Distributed streaming 0.729, Databases 0.696, Distributed computing 0.676 | Distributed streaming | Distributed streaming, Databases, Distributed computing |
| https://kafka.apache.org/43/design/design/ | html | Distributed streaming | Distributed streaming 0.794, Databases 0.751, Distributed computing 0.742 | unclassified | Distributed streaming, Databases, Distributed computing |
| https://kafka.apache.org/43/getting-started/introduction/ | html | Distributed streaming | Distributed streaming 0.826, Databases 0.706, Distributed computing 0.705 | Distributed streaming | Distributed streaming, Databases, Distributed computing |
| https://kafka.apache.org/43/getting-started/quickstart/ | html | Distributed streaming | Distributed streaming 0.715, Distributed computing 0.653, Databases 0.643 | Distributed streaming | Distributed streaming, Distributed computing |
| https://spark.apache.org/docs/4.0.1/sql-data-sources-load-save-functions.html | html | Distributed computing | Databases 0.701, Distributed computing 0.685, Distributed streaming 0.672 | Distributed computing | Databases, Distributed computing, Distributed streaming |
| https://spark.apache.org/docs/4.0.1/submitting-applications.html | html | Distributed computing | Distributed computing 0.718, Distributed streaming 0.660, Databases 0.640 | unclassified | Distributed computing, Distributed streaming |
| https://www.postgresql.org/docs/18/indexes-types.html | html | Databases | Databases 0.733, Distributed streaming 0.669, Distributed computing 0.664 | Databases | Databases, Distributed streaming, Distributed computing |
| https://www.postgresql.org/docs/18/transaction-iso.html | html | Databases | Databases 0.776, Distributed streaming 0.720, Distributed computing 0.675 | Databases | Databases, Distributed streaming, Distributed computing |
| https://www.postgresql.org/docs/18/using-explain.html | html | Databases | Databases 0.738, Distributed computing 0.702, Distributed streaming 0.656 | Databases | Databases, Distributed computing, Distributed streaming |

### Unclassified threshold

| Fixture | Split | Topic | Chunks | Top category (cosine) | Unclassified (proposal) |
|---|---|---|---|---|---|
| oot-01 | calibration | gardening | 3 | Distributed streaming 0.562 | yes |
| oot-02 | calibration | chess | 2 | Databases 0.580 | yes |
| oot-03 | calibration | personal finance | 2 | Databases 0.601 | yes |
| oot-04 | calibration | web page layout | 2 | Databases 0.591 | yes |
| oot-05 | calibration | version control | 3 | Databases 0.616 | yes |
| oot-06 | held_out | cooking | 2 | Distributed streaming 0.507 | yes |
| oot-07 | held_out | birdwatching | 2 | Databases 0.505 | yes |
| oot-08 | held_out | bicycle maintenance | 2 | Distributed computing 0.528 | yes |
| oot-09 | held_out | home networking | 3 | Databases 0.594 | yes |
| oot-10 | held_out | document typesetting | 3 | Databases 0.657 | no |

In-topic top-1 min / median / max: 0.682148 / 0.740769 / 0.825978. Calibration out-of-topic: 0.562320 / 0.590976 / 0.616049.

Proposed threshold 0.649099 (`balanced-accuracy-midpoint-v1`), margin 0.033049, separable: 20 of 20 in-topic documents classified, 5 of 5 calibration fixtures unclassified, 0 leave-one-out errors.
Held out, judged by the active threshold: 0.800 (4 of 5, 95% 0.376-0.964) unclassified; cooking article unclassified: yes.

To adopt, set these in `[enrichment]` (this run becomes the calibration run):

```toml
[enrichment]
unclassified_threshold = 0.649099
calibration_run_id = "enrichment_e8b952d01ba84d1f93320478eb5dab0a"
similarity_config_id = "cs_f138c575d3b18c6553bf96f57e55f743f6637eb359e7d24fbbd95b63451e3803"
```

## Real-corpus checks (AC-07.2, AC-07.3, AC-08.1, AC-09.3)

- AC-07.2: 6386 entity rows, 0 with a chunk, document or offset that does not match: met.
- AC-07.3 `{'entity': 'PostgreSQL'}`: bm25 20 results, 0 outside the filter; vector 20 results, 0 outside the filter: met.
- AC-09.3 `{'category': 'Databases'}`: bm25 20 results, 0 outside the filter; vector 20 results, 0 outside the filter: met.
- AC-08.1: 20 documents, invalid keyphrase lists: none: met.

## Run times

Stages (s): segmentation 8.333, entities 1.098, keyphrases 1.133, classification 8.469, corpus_checks 4.751, enrichment_times 1.244

In-memory extraction per document (P9-12):

| Document | Chunks | Characters | Entities | Entities ms | Keyphrases ms |
|---|---|---|---|---|---|
| postgresql-18-transaction-system.txt | 75 | 59061 | 537 | 47.3 | 63.6 |
| postgresql-18-tutorial-advanced-features.pdf | 30 | 23482 | 242 | 21.8 | 26.7 |
| postgresql-18-tutorial-getting-started.pdf | 18 | 13792 | 65 | 12.0 | 15.2 |
| postgresql-18-tutorial-sql-language.pdf | 37 | 25930 | 337 | 25.4 | 34.2 |
| spark-4.0.1-cluster-overview.md | 13 | 7800 | 106 | 8.3 | 9.0 |
| spark-4.0.1-hardware-provisioning.md | 9 | 4971 | 60 | 4.8 | 6.9 |
| spark-4.0.1-tuning.md | 38 | 25330 | 205 | 21.8 | 29.4 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html | 22 | 12949 | 255 | 15.9 | 16.3 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html | 65 | 42813 | 889 | 50.9 | 67.8 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html | 21 | 14148 | 217 | 15.0 | 20.2 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/tasks.html | 28 | 17647 | 294 | 19.9 | 20.4 |
| https://kafka.apache.org/43/configuration/producer-configs/ | 123 | 54176 | 505 | 47.7 | 62.5 |
| https://kafka.apache.org/43/design/design/ | 123 | 85823 | 734 | 101.6 | 126.3 |
| https://kafka.apache.org/43/getting-started/introduction/ | 18 | 10863 | 122 | 10.5 | 12.4 |
| https://kafka.apache.org/43/getting-started/quickstart/ | 20 | 11235 | 210 | 11.7 | 18.2 |
| https://spark.apache.org/docs/4.0.1/sql-data-sources-load-save-functions.html | 26 | 18852 | 412 | 21.2 | 30.2 |
| https://spark.apache.org/docs/4.0.1/submitting-applications.html | 20 | 12256 | 215 | 14.8 | 19.2 |
| https://www.postgresql.org/docs/18/indexes-types.html | 15 | 9041 | 116 | 14.2 | 10.5 |
| https://www.postgresql.org/docs/18/transaction-iso.html | 40 | 30102 | 300 | 36.3 | 37.6 |
| https://www.postgresql.org/docs/18/using-explain.html | 75 | 54446 | 565 | 64.4 | 48.6 |

## Provenance

```json
{
 "category_descriptions_sha256": "67d706a84744b9cde5acad6f5e5623e136d8bcca09fd3d9477383169591a2f00",
 "corpus": {
  "content_drift": [],
  "corpus_fingerprint": "e8713f0c15eeb6db2c801a319c2324507302242c6265b8fff1ae67db63a2c4b5",
  "excluded_eligible_documents": 1,
  "manifest_dataset_id": "techdocqa-reference-2026-10-24-v2",
  "manifest_fingerprint": "40229e3caebc8816d6ad98d36bddc10eb133deb7d3b1c416f8a1331b9d75591a",
  "manifest_status": "frozen",
  "scope_documents": 20,
  "searchable_chunks": 816,
  "searchable_documents": 20,
  "unavailable": {}
 },
 "enrichment_config": {
  "classifier_config_id": "cc_b300c609bfa2ad4d6d467c74b8e25b374fd4442a6d8f6c2dd6b3c0eb7bf4ef18",
  "enrichment_config_id": "en_b5e90c2bc4857fc2ec5251e9450f23f10db847317083c3d3978692e45feeb925",
  "entity_config_id": "ec_f26323871a9c7985bcefa07de9fdc7ce6df594c687a7ce1fbee1e146437832d2",
  "keyphrase_config_id": "kc_faec6d15ce98cb3a62163e81b4b4ae9cb5441d9d83d00bbc920133d556f5adce"
 },
 "gazetteer_sha256": "7aa9d0f725d871e49a129539ee85a72f9f50c5a69f4d5f697b764de0c52e8744",
 "gold_files": {
  "entities": {
   "path": "datasets/nlp/entities_gold.jsonl",
   "rows": 20,
   "sha256": "b82e2f094e1a86546482a82f06511b600270ee3103e5a4eda4837c5b14578bc4",
   "status": "frozen"
  },
  "keyphrases": {
   "path": "datasets/nlp/keyphrases_gold.jsonl",
   "rows": 5,
   "sha256": "320534b487f0c12bff22f2fbe050d13016de6c5e7609e1a8df1bbebdab7ed88d",
   "status": "frozen"
  },
  "segmentation": {
   "path": "datasets/nlp/segmentation_gold.jsonl",
   "rows": 20,
   "sha256": "fd4aaf641fdd0648957de4c6df972f5e5160a0477263aaa890605343bb551294",
   "status": "frozen"
  }
 },
 "keyphrase_policy": "technical-ngrams-v1",
 "keyphrases_available": true,
 "nlp_libraries": {
  "nltk": "3.10.4",
  "rake-nltk": "1.0.6",
  "spacy": "3.8.18"
 },
 "out_of_topic": {
  "path": "datasets/nlp/out_of_topic.jsonl",
  "sha256": "e8180839ea52c2af552172ca773049f778f02b18f00fc2ad2e4a2b280b91a71f"
 },
 "requirements_lock_sha256": "0818d0d24aa770fff4da8c22f3e32d7d21c9cabf17172f2e4cf0158490428d3d",
 "segmenter_available": true,
 "spacy_model": null
}
```

## Notes

- Indicative only: the gold sets are the requirement minimums (P9-9). Every rate carries its denominator and a Wilson 95% interval; a target met only at the point estimate is reported that way.
- The gazetteer changed after the entity sample was drawn, so the entity figures are tuned, not held out (P9-9).
- The n-gram keyphrase policy was tuned on this key-term set, so its key-term figures are tuned, not held out. The RAKE variants were not tuned on it.
- The 20 public documents both calibrate the unclassified threshold and are assessed by AC-09.1, so that side is not independent. The held-out out-of-topic fixtures were not used to choose the threshold.
- Category scores are cosine similarities between a document's mean chunk vector and each description vector, not probabilities.
- DDIA and every other document outside the manifest's evaluation scope were not read.
