# Enrichment evaluation enrichment_5d0f6cdcc0bd41ddaa2a05dc5bf0f029

- Date: 2026-11-13T05:43:06.066505+00:00, 31.181 s
- Corpus: `techdocqa-reference-2026-10-24-v2`, 20 of 20 documents, fingerprint `e8713f0c15eeb6db2c801a319c2324507302242c6265b8fff1ae67db63a2c4b5`
- Code: 2982ac897c45c44afee2ad60b6b67c5f447bcc96 (dirty: True); enrichment configuration `en_b5e90c2bc4857fc2ec5251e9450f23f10db847317083c3d3978692e45feeb925`
- Gazetteer SHA-256 `7aa9d0f725d871e49a129539ee85a72f9f50c5a69f4d5f697b764de0c52e8744`; category descriptions SHA-256 `67d706a84744b9cde5acad6f5e5623e136d8bcca09fd3d9477383169591a2f00`
- Gold data: segmentation awaiting gold data; entities frozen (`85ec90a61d46`, 32 rows); keyphrases frozen (`52bbfd8d74ec`, 15 rows)
- Out-of-topic fixtures: `datasets/nlp/out_of_topic.jsonl` SHA-256 `e8180839ea52c2af552172ca773049f778f02b18f00fc2ad2e4a2b280b91a71f`

## Acceptance

| Criterion | Target | Result | Verdict |
|---|---|---|---|
| AC-06.4 | boundary F1 >= 0.95 on >= 50 sentences (spaCy policy) | n/a | awaiting gold data |
| AC-07.4 | precision >= 0.80, recall >= 0.60 on >= 20 chunks | 0.892 / 0.619 | met at point estimate only |
| AC-08.3 | mean share of key terms in the top 10 >= 0.50 over 5 documents | 0.239 | not met |
| AC-09.1 | accuracy >= 0.85, >= 2 documents per category | 0.950 | met at point estimate only |
| AC-09.2 | the out-of-topic cooking article is unclassified (result: held-out fixtures unclassified) | 0.800 | met |
| AC-07.2 (real corpus) | see the corpus checks | n/a | met |
| AC-07.3 (real corpus) | see the corpus checks | n/a | met |
| AC-08.1 (real corpus) | see the corpus checks | n/a | met |
| AC-09.3 (real corpus) | see the corpus checks | n/a | met |

## Sentence boundaries (AC-06.4, P9-2)

Not measured: awaiting gold data.

## Entities (AC-07.4)

Verified mentions (confidence >= 0.5) against the labels, on (chunk, normalized text, type), micro-averaged over 32 chunks. Tuned: no.

- Precision 0.892 (166 of 186, 95% 0.840-0.929)
- Recall 0.619 (166 of 268, 95% 0.560-0.675)
- F1 0.731

| Type | Precision | Recall |
|---|---|---|
| TECHNOLOGY | 1.000 (26 of 26, 95% 0.871-1.000) | 0.788 (26 of 33, 95% 0.623-0.893) |
| COMPONENT | 0.913 (21 of 23, 95% 0.732-0.976) | 0.724 (21 of 29, 95% 0.543-0.853) |
| CONCEPT | 0.875 (28 of 32, 95% 0.719-0.950) | 0.301 (28 of 93, 95% 0.217-0.401) |
| PROTOCOL | 1.000 (1 of 1, 95% 0.206-1.000) | 1.000 (1 of 1, 95% 0.206-1.000) |
| IDENTIFIER | 0.865 (90 of 104, 95% 0.787-0.918) | 0.804 (90 of 112, 95% 0.721-0.867) |

| Rule family | Precision |
|---|---|
| gazetteer | 0.931 (81 of 87, 95% 0.858-0.968) |
| pattern | 0.859 (85 of 99, 95% 0.776-0.914) |

| Technology | Gold | Predicted | Matched | Precision | Recall |
|---|---|---|---|---|---|
| Apache Airflow | 101 | 70 | 61 | 0.871 | 0.604 |
| Apache Kafka | 45 | 29 | 28 | 0.966 | 0.622 |
| Apache Spark | 69 | 57 | 51 | 0.895 | 0.739 |
| PostgreSQL | 53 | 30 | 26 | 0.867 | 0.491 |

| Format | Gold | Predicted | Matched | Precision | Recall |
|---|---|---|---|---|---|
| html | 189 | 131 | 115 | 0.878 | 0.608 |
| md | 42 | 33 | 30 | 0.909 | 0.714 |
| pdf | 24 | 15 | 15 | 1.000 | 0.625 |
| txt | 13 | 7 | 6 | 0.857 | 0.462 |

| Ambiguous-name stratum | Gold | Predicted | Matched | Precision | Recall |
|---|---|---|---|---|---|
| False | 124 | 82 | 77 | 0.939 | 0.621 |
| True | 144 | 104 | 89 | 0.856 | 0.618 |

Diagnostics: ignoring type, precision 0.925 and recall 0.642; including unverified mentions, precision 0.881 and recall 0.634.

Errors:

- E21: false positives TaskFlow API (COMPONENT, gazetteer, labeled CONCEPT), TaskGroups (IDENTIFIER, identifier-camel, labeled CONCEPT); missed connections (CONCEPT), hooks (CONCEPT), pools (CONCEPT), taskflow api (CONCEPT), taskgroups (CONCEPT), tasks (CONCEPT), worker (COMPONENT), workers (COMPONENT)
- E22: false positives catchup (CONCEPT, gazetteer), self.url (IDENTIFIER, identifier); missed @dag (IDENTIFIER), httpx (IDENTIFIER), pendulum (IDENTIFIER)
- E23: false positives Dag (CONCEPT, gazetteer); missed .airflowignore (IDENTIFIER), dag bundle (CONCEPT), processor (COMPONENT), python (TECHNOLOGY)
- E24: false positives none; missed heartbeat (CONCEPT), liveness probe (CONCEPT), tasks (CONCEPT), worker (COMPONENT), zombie tasks (CONCEPT)
- E25: false positives none; missed leaf nodes (CONCEPT), leaves (CONCEPT), tasks (CONCEPT), terminal states (CONCEPT)
- E26: false positives exception.response (IDENTIFIER, identifier), exception.response.headers.get (IDENTIFIER, identifier), exception.response.status_code (IDENTIFIER, identifier); missed datetime (IDENTIFIER), isinstance (IDENTIFIER), requests (IDENTIFIER), retry-after (IDENTIFIER), timedelta (IDENTIFIER)
- E27: false positives Operators (CONCEPT, gazetteer); missed asyncio (TECHNOLOGY), deferrable operators (CONCEPT), deferred tasks (CONCEPT), event loop (CONCEPT), human-in-the-loop (CONCEPT), pod (CONCEPT), tasks (CONCEPT), triggerer (COMPONENT), triggers (CONCEPT), worker (COMPONENT)
- E28: false positives none; missed airflow dags trigger (IDENTIFIER)
- E29: false positives none; missed events (CONCEPT), key (CONCEPT), replication (CONCEPT), topic-partition (CONCEPT), topic-partitions (CONCEPT)
- E30: false positives none; missed messages (CONCEPT), messaging system (CONCEPT)
- E31: false positives none; missed message (CONCEPT)
- E33: false positives producer (COMPONENT, gazetteer); missed events (CONCEPT), messaging systems (CONCEPT)
- E34: false positives none; missed connectors (CONCEPT), messages (CONCEPT), sink connector (CONCEPT), source connector (CONCEPT)
- E35: false positives none; missed exponential backoff (CONCEPT), json web key set (CONCEPT), jwks (CONCEPT)
- E37: false positives configuration.html#spark-properties (IDENTIFIER, identifier); missed kryo (TECHNOLOGY), serializable (IDENTIFIER), serializer (CONCEPT), serializers (CONCEPT), shuffling (CONCEPT), twitter chill (TECHNOLOGY)
- E38: false positives URLs (IDENTIFIER, identifier-camel); missed application jar (CONCEPT)
- E39: false positives none; missed options (IDENTIFIER), parquet (TECHNOLOGY), string (IDENTIFIER)
- E40: false positives rdd-programming-guide.html#rdd-persistence (IDENTIFIER, identifier); missed java serialization (CONCEPT), kryo (TECHNOLOGY)
- E41: false positives EXISTS (IDENTIFIER, sql-keyword), NOT (IDENTIFIER, sql-keyword); missed data source (CONCEPT), if not exists (IDENTIFIER)
- E43: false positives JVMs (IDENTIFIER, identifier-camel, labeled TECHNOLOGY); missed jvms (TECHNOLOGY)
- E44: false positives none; missed main (IDENTIFIER), standalone manager (COMPONENT), worker node (COMPONENT)
- E45: false positives BitmapAnd (IDENTIFIER, identifier-camel, labeled CONCEPT), BitmapOr (IDENTIFIER, identifier-camel, labeled CONCEPT), MergeAppend (IDENTIFIER, identifier-camel, labeled CONCEPT); missed append (CONCEPT), bitmapand (CONCEPT), bitmapor (CONCEPT), mergeappend (CONCEPT), partitioned table (CONCEPT), plan node (CONCEPT), plan nodes (CONCEPT)
- E46: false positives none; missed abort record (CONCEPT), commit record (CONCEPT), relations (CONCEPT), synchronous commit (CONCEPT), transaction (CONCEPT)
- E47: false positives none; missed gettimeofday (IDENTIFIER), serialize (IDENTIFIER)
- E48: false positives WAL (CONCEPT, gazetteer); missed ndatas (IDENTIFIER), wal record (CONCEPT)
- E49: false positives none; missed index (CONCEPT), indexes (CONCEPT)
- E50: false positives none; missed cd (IDENTIFIER), make (IDENTIFIER), mydb (IDENTIFIER), psql (IDENTIFIER)
- E51: false positives none; missed atomic (CONCEPT), transaction (CONCEPT), transactions (CONCEPT)
- E52: false positives none; missed transaction (CONCEPT), transactions (CONCEPT)

## Key terms (AC-08.3, P9-5)

Configured variant `ngram/with_code` (n-gram policy or RAKE metric / code blocks); the best on this gold set is `ngram/without_code`. N-gram policy tuned on this set: no.

| Variant | Mean hit rate | Pooled terms | Mean lenient hit rate (diagnostic) | By size (mean hit rate, documents) |
|---|---|---|---|---|
| ngram/with_code | 0.239 | 0.236 (51 of 216, 95% 0.184-0.297) | 0.461 | 30 chunks or fewer: 0.272 (7); over 30 chunks: 0.210 (8) |
| ngram/without_code | 0.243 | 0.241 (52 of 216, 95% 0.189-0.302) | 0.443 | 30 chunks or fewer: 0.262 (7); over 30 chunks: 0.226 (8) |
| degree_to_frequency/with_code | 0.005 | 0.005 (1 of 216, 95% 0.001-0.026) | 0.123 | 30 chunks or fewer: 0.010 (7); over 30 chunks: 0.000 (8) |
| degree_to_frequency/without_code | 0.010 | 0.009 (2 of 216, 95% 0.003-0.033) | 0.155 | 30 chunks or fewer: 0.020 (7); over 30 chunks: 0.000 (8) |
| word_degree/with_code | 0.046 | 0.046 (10 of 216, 95% 0.025-0.083) | 0.188 | 30 chunks or fewer: 0.040 (7); over 30 chunks: 0.052 (8) |
| word_degree/without_code | 0.033 | 0.032 (7 of 216, 95% 0.016-0.065) | 0.183 | 30 chunks or fewer: 0.031 (7); over 30 chunks: 0.035 (8) |
| word_frequency/with_code | 0.042 | 0.042 (9 of 216, 95% 0.022-0.077) | 0.178 | 30 chunks or fewer: 0.030 (7); over 30 chunks: 0.052 (8) |
| word_frequency/without_code | 0.033 | 0.032 (7 of 216, 95% 0.016-0.065) | 0.187 | 30 chunks or fewer: 0.031 (7); over 30 chunks: 0.035 (8) |

ngram/with_code:

| Document | Technology | Format | Chunks | Hits | Missed | Top 10 |
|---|---|---|---|---|---|---|
| K06 | Apache Airflow | html | 22 | 6 of 13 | re-run, terminal states, leaf nodes, start_date, timetable, external triggers, dag_run.conf | dag, dag run, data interval, task instance, task, logical date, catchup, scheduler, backfill, trigger rule |
| K07 | Apache Airflow | html | 28 | 3 of 14 | retry policy, dependencies, upstream, operators, execution_timeout, retries, task instance heartbeat timeout, exceptionretrypolicy, retryrule, airflowfailexception, executor_config | task, task instance, dag, sensor, retry, operator, worker, data interval, policy, exception |
| K08 | Apache Airflow | html | 65 | 5 of 15 | dependencies, branching, schedule, taskgroup, .airflowignore, dag bundle, default_args, logical date, deadline alerts, dags_folder | dag, dag run, tasks, run, operator, python, trigger rules, data interval, upstream tasks, import |
| K09 | Apache Kafka | html | 20 | 5 of 13 | quickstart, console producer, console consumer, connectors, kafka-topics.sh, source connector, sink connector, kafka environment | topic, kafka connect, docker, kafka streams, events, consumer, connector, kafka topic, run, docker image |
| K10 | Apache Kafka | html | 123 | 0 of 15 | producer configs, acks, bootstrap.servers, batch.size, linger.ms, enable.idempotence, retries, compression.type, delivery.timeout.ms, transactional.id, partitioner.class, security.protocol, sasl.jaas.config, jwt assertion, ssl.keystore.location | broker, valid, importance, producer, null valid, partition, client, low, medium, record |
| K11 | Apache Kafka | html | 123 | 1 of 15 | replication, isr, message delivery semantics, exactly-once, transactions, share group, quota, pagecache, batching, leader election, replicated log, consumer position, sendfile, static membership | consumer, broker, replicas, producer, message, partition, topic, log, log compaction, in-sync replicas |
| K12 | Apache Spark | md | 13 | 5 of 14 | cluster mode overview, worker nodes, deploy mode, tasks, job scheduling, stages, yarn, kubernetes, spark-submit | cluster manager, driver, driver program, td, executors, cluster, application, tr, sparkcontext, worker |
| K13 | Apache Spark | html | 20 | 3 of 15 | submitting applications, master url, --deploy-mode, client mode, dependencies, --master, application-jar, --py-files, --jars, --properties-file, assembly jar, --packages | deploy mode, worker, cluster mode, cluster, spark-submit, cluster manager, python, application, driver, spark standalone |
| K14 | Apache Spark | html | 26 | 3 of 14 | generic load/save functions, savemode, saveastable, persistent tables, bucketby, partitionby, hive metastore, orc, json, spark.sql.sources.default, csv | find full, spark repo, option, data source, dataframe, code, table, parquet, name, sql |
| K15 | Apache Spark | md | 38 | 2 of 14 | memory tuning, data serialization, kryo, gc, serialized form, level of parallelism, data locality, spark.memory.fraction, java serialization, young generation, broadcast variable, caching | java, rdd, objects, memory, task, garbage collection, tuning, memory usage, size, executor |
| K16 | PostgreSQL | pdf | 30 | 1 of 14 | window functions, savepoint, views, foreign keys, inheritance, transaction block, window frame, over clause, partition by, referential integrity, advanced features, rollback to, aggregate function | window function, partition, rows, table, transaction, name, cities, salary, sql, update |
| K17 | PostgreSQL | pdf | 37 | 2 of 15 | aggregate functions, join, create table, insert, where clause, update, delete, group by, having, order by, outer join, data type, copy | san francisco, city, rows, table, weather, sql, select, temp_lo, columns, aggregate |
| K18 | PostgreSQL | html | 40 | 6 of 15 | serialization anomaly, predicate locks, snapshot isolation, phantom read, dirty read, nonrepeatable read, concurrent transactions, snapshot, select for update | isolation level, repeatable read, transaction, read committed, serializable, transaction isolation, read, serialization anomalies, serialization failures, serializable transactions |
| K19 | PostgreSQL | txt | 75 | 5 of 15 | transaction system, savepoints, asynchronous commit, snapshot, pg_subtrans, pg_xact, procarraylock, getsnapshotdata, full-page image, committransactioncommand | wal, transaction, wal record, commit, xid, change, buffer, subtransactions, lsn, write |
| K20 | PostgreSQL | html | 75 | 4 of 15 | planner, plan node, cost estimates, sequential scan, bitmap index scan, bitmap heap scan, merge join, hash join, nested-loop join, subplan, filter condition | index scan, query plan, rows, explain, explain analyze, seq scan, cost, index, scan, plan |

ngram/without_code:

| Document | Technology | Format | Chunks | Hits | Missed | Top 10 |
|---|---|---|---|---|---|---|
| K06 | Apache Airflow | html | 22 | 6 of 13 | re-run, terminal states, leaf nodes, start_date, timetable, external triggers, dag_run.conf | dag run, dag, data interval, task instance, task, logical date, scheduler, catchup, trigger rule, backfill |
| K07 | Apache Airflow | html | 28 | 3 of 14 | retry policy, dependencies, upstream, operators, execution_timeout, retries, task instance heartbeat timeout, exceptionretrypolicy, retryrule, airflowfailexception, executor_config | task, task instance, dag, sensor, operator, worker, retry, data interval, policy, run |
| K08 | Apache Airflow | html | 65 | 6 of 15 | dependencies, branching, schedule, taskgroup, .airflowignore, dag bundle, default_args, deadline alerts, dags_folder | dag, dag run, tasks, run, operator, python, trigger rules, data interval, upstream tasks, logical date |
| K09 | Apache Kafka | html | 20 | 5 of 13 | quickstart, console producer, console consumer, connectors, kafka-topics.sh, source connector, sink connector, kafka environment | topic, kafka connect, kafka streams, consumer, docker, events, connector, kafka topic, docker image, run |
| K10 | Apache Kafka | html | 123 | 0 of 15 | producer configs, acks, bootstrap.servers, batch.size, linger.ms, enable.idempotence, retries, compression.type, delivery.timeout.ms, transactional.id, partitioner.class, security.protocol, sasl.jaas.config, jwt assertion, ssl.keystore.location | broker, valid, importance, producer, null valid, partition, client, low, medium, record |
| K11 | Apache Kafka | html | 123 | 1 of 15 | replication, isr, message delivery semantics, exactly-once, transactions, share group, quota, pagecache, batching, leader election, replicated log, consumer position, sendfile, static membership | consumer, broker, replicas, producer, message, partition, topic, log, log compaction, in-sync replicas |
| K12 | Apache Spark | md | 13 | 5 of 14 | cluster mode overview, application, deploy mode, tasks, job scheduling, stages, yarn, kubernetes, spark-submit | cluster manager, driver program, executors, cluster, applications, sparkcontext, run, worker, cluster mode, worker nodes |
| K13 | Apache Spark | html | 20 | 2 of 15 | spark-submit, submitting applications, master url, --deploy-mode, client mode, dependencies, --master, application-jar, --py-files, --jars, --properties-file, assembly jar, --packages | worker, cluster manager, python, cluster, driver, application, deploy mode, executor, cluster mode, run spark |
| K14 | Apache Spark | html | 26 | 3 of 14 | generic load/save functions, savemode, saveastable, parquet, bucketby, partitionby, hive metastore, orc, json, spark.sql.sources.default, csv | find full, spark repo, data source, code, dataframe, sql, table, partition, persistent tables, table path |
| K15 | Apache Spark | md | 38 | 2 of 14 | memory tuning, data serialization, kryo, gc, serialized form, level of parallelism, data locality, spark.memory.fraction, java serialization, young generation, broadcast variable, caching | java, rdd, objects, memory, task, garbage collection, tuning, memory usage, size, executor |
| K16 | PostgreSQL | pdf | 30 | 1 of 14 | window functions, savepoint, views, foreign keys, inheritance, transaction block, window frame, over clause, partition by, referential integrity, advanced features, rollback to, aggregate function | window function, rows, partition, table, transaction, sql, salary, update, cities, balance |
| K17 | PostgreSQL | pdf | 37 | 2 of 15 | aggregate functions, join, create table, insert, where clause, update, delete, group by, having, order by, outer join, data type, copy | san francisco, rows, table, city, sql, weather, select, columns, aggregate, select city |
| K18 | PostgreSQL | html | 40 | 6 of 15 | serialization anomaly, predicate locks, snapshot isolation, phantom read, dirty read, nonrepeatable read, concurrent transactions, snapshot, select for update | isolation level, repeatable read, transaction, read committed, serializable, transaction isolation, serialization anomalies, read, serialization failures, serializable transactions |
| K19 | PostgreSQL | txt | 75 | 5 of 15 | transaction system, savepoints, asynchronous commit, snapshot, pg_subtrans, pg_xact, procarraylock, getsnapshotdata, full-page image, committransactioncommand | wal, transaction, wal record, commit, xid, subtransactions, change, lsn, write, buffer |
| K20 | PostgreSQL | html | 75 | 5 of 15 | explain, explain analyze, cost estimates, bitmap index scan, bitmap heap scan, merge join, hash join, nested-loop join, subplan, filter condition | index scan, node, planner, rows, plan, plan node, scan, index, query plan, sequential scan |

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
calibration_run_id = "enrichment_5d0f6cdcc0bd41ddaa2a05dc5bf0f029"
similarity_config_id = "cs_f138c575d3b18c6553bf96f57e55f743f6637eb359e7d24fbbd95b63451e3803"
```

## Real-corpus checks (AC-07.2, AC-07.3, AC-08.1, AC-09.3)

- AC-07.2: 6386 entity rows, 0 with a chunk, document or offset that does not match: met.
- AC-07.3 `{'entity': 'PostgreSQL'}`: bm25 20 results, 0 outside the filter; vector 20 results, 0 outside the filter: met.
- AC-09.3 `{'category': 'Databases'}`: bm25 20 results, 0 outside the filter; vector 20 results, 0 outside the filter: met.
- AC-08.1: 20 documents, invalid keyphrase lists: none: met.

## Run times

Stages (s): segmentation 0.0, entities 7.908, keyphrases 5.373, classification 9.879, corpus_checks 5.303, enrichment_times 1.211

In-memory extraction per document (P9-12):

| Document | Chunks | Characters | Entities | Entities ms | Keyphrases ms |
|---|---|---|---|---|---|
| postgresql-18-transaction-system.txt | 75 | 59061 | 537 | 46.6 | 50.1 |
| postgresql-18-tutorial-advanced-features.pdf | 30 | 23482 | 242 | 21.0 | 35.3 |
| postgresql-18-tutorial-getting-started.pdf | 18 | 13792 | 65 | 13.1 | 12.5 |
| postgresql-18-tutorial-sql-language.pdf | 37 | 25930 | 337 | 48.5 | 26.6 |
| spark-4.0.1-cluster-overview.md | 13 | 7800 | 106 | 18.0 | 15.8 |
| spark-4.0.1-hardware-provisioning.md | 9 | 4971 | 60 | 6.1 | 5.2 |
| spark-4.0.1-tuning.md | 38 | 25330 | 205 | 22.1 | 23.0 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html | 22 | 12949 | 255 | 13.1 | 13.2 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html | 65 | 42813 | 889 | 42.7 | 39.5 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html | 21 | 14148 | 217 | 12.9 | 13.6 |
| https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/tasks.html | 28 | 17647 | 294 | 17.1 | 16.6 |
| https://kafka.apache.org/43/configuration/producer-configs/ | 123 | 54176 | 505 | 47.6 | 67.8 |
| https://kafka.apache.org/43/design/design/ | 123 | 85823 | 734 | 83.2 | 118.9 |
| https://kafka.apache.org/43/getting-started/introduction/ | 18 | 10863 | 122 | 21.6 | 20.8 |
| https://kafka.apache.org/43/getting-started/quickstart/ | 20 | 11235 | 210 | 17.7 | 13.4 |
| https://spark.apache.org/docs/4.0.1/sql-data-sources-load-save-functions.html | 26 | 18852 | 412 | 35.3 | 14.6 |
| https://spark.apache.org/docs/4.0.1/submitting-applications.html | 20 | 12256 | 215 | 11.6 | 10.6 |
| https://www.postgresql.org/docs/18/indexes-types.html | 15 | 9041 | 116 | 17.1 | 16.0 |
| https://www.postgresql.org/docs/18/transaction-iso.html | 40 | 30102 | 300 | 40.9 | 24.3 |
| https://www.postgresql.org/docs/18/using-explain.html | 75 | 54446 | 565 | 63.4 | 70.7 |

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
   "path": "datasets/nlp/round2/entities_gold.jsonl",
   "rows": 32,
   "sha256": "85ec90a61d46289576e60c44e85bbb9a4ea9b37b23815459c943d114e8ac2735",
   "status": "frozen"
  },
  "keyphrases": {
   "path": "datasets/nlp/round2/keyphrases_gold.jsonl",
   "rows": 15,
   "sha256": "52bbfd8d74ec28eb299cafdd4fdfdf387aab1b7181e9f1aa1054fdab826ea62f",
   "status": "frozen"
  },
  "segmentation": {
   "path": "datasets/nlp/round2/segmentation_gold.jsonl",
   "status": "awaiting_gold_data"
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
- Awaiting frozen gold data: segmentation. Those criteria are not measured until the owner labels and freezes them (datasets/nlp/review_log.md).
- The 20 public documents both calibrate the unclassified threshold and are assessed by AC-09.1, so that side is not independent. The held-out out-of-topic fixtures were not used to choose the threshold.
- Category scores are cosine similarities between a document's mean chunk vector and each description vector, not probabilities.
- DDIA and every other document outside the manifest's evaluation scope were not read.
