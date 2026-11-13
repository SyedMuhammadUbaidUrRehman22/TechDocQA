# Smoke benchmark review log

Benchmark: [benchmark_smoke.jsonl](benchmark_smoke.jsonl), 30 questions, 20 answerable and 10 unanswerable. Corpus: the frozen public reference `techdocqa-reference-2026-10-24-v2` (20 documents). The private DDIA supplement is excluded from every run and carries no labels.

## Status

**Reviewed 2026-11-03.** Claude Code drafted all 30 questions on 2026-11-03 at the project owner's request, from the stored chunk text of the public reference. The project owner (Git user HMSalmanSaeed) reviewed them the same day and accepted all 30 without changes, so every question is now marked `"review": "reviewed"`. No disagreements were raised. The review was a person reviewing a machine-written draft; the record does not show which checks below were applied to each question.

## How labels work

Each answerable question lists one or more relevant items. An item is a `source_key` from the frozen manifest plus either a verbatim `anchor` from the document or a `section` heading path, with a `grade`:

- `2`: the passage answers the question.
- `1`: the passage supports the answer, or answers part of it.
- `0`: labeled not relevant; it never counts as a hit.

Anchors are matched case-insensitively with whitespace collapsed, against the current chunks of the active version, on every run. They name text, not chunk IDs, so they survive re-chunking. If a source is deleted, withdrawn or leaves the evaluation scope, or an anchor stops matching, the run flags the question and excludes it from the metrics. The file is not edited (AC-21.3).

On 2026-11-03 every anchor resolved to at least one current chunk.

## What the reviewer checks

For each answerable question:

1. The question is answerable from the labeled passages alone.
2. No other passage in the public reference answers it as well and is missing from the labels. A missing passage makes the metrics look worse than retrieval really is.
3. Each grade is right.
4. The wording does not copy the anchor so closely that BM25 is favored.

For each unanswerable question, nothing in the 20 public documents answers it. Then change `draft` to `reviewed` for each accepted question. The edit changes the dataset hash, which is intended.

## Points for the reviewer

| Question | Point |
|---|---|
| smoke-ood-03 | The Airflow tasks page says a worker "failed its liveness probe" under Kubernetes. It does not explain how to configure one, so the question was kept as unanswerable. It is the hardest negative for BM25. |
| smoke-kafka-01 | There are two items: the batching behavior and the default value. They are in neighboring chunks, so finding only one gives recall 0.5. |
| smoke-kafka-03, smoke-airflow-05 | A grade 1 item counts as relevant for Recall and MRR in P0. Graded gain only matters for P1 nDCG. |
| smoke-spark-05 | The answer is split across two documents, the cluster overview glossary and the `--deploy-mode` option list. Both are labeled. |
| smoke-spark-03 | The anchor keeps the source Markdown emphasis (`**4-8 disks**`, `_without_`), because chunk text is not stripped of markup. |
| All | The questions were written after reading the passages. Wording close to the source favors BM25 and makes the set easier than real user questions. |

## Disagreements

| Date | Question | Reviewer's position | Resolution |
|---|---|---|---|
| 2026-11-03 | All 30 | Accepted as drafted | No change |

# Full benchmark review log (Phase 10)

Benchmark: [benchmark_full.jsonl](benchmark_full.jsonl), 50 questions: the 30 smoke questions, byte for byte, followed by 20 new ones (`full-*`). That gives 36 answerable and 14 unanswerable (28%). The corpus is the same frozen public reference, and DDIA carries no labels.

## Status

**Reviewed and frozen 2026-11-13.** Claude Code drafted the 20 new questions from the stored chunk text of the public reference, under P10-8 (draft SHA-256 `2754e5b2a118f151893b7ae999fbddcd5ce9b2e9133342d38ed3610e46a3ca34`, commit c550a8e). The project owner reviewed them the same day, in the Claude Code session that drafted them, and accepted all 20 without changes. The reviewer's identity was not stated beyond that.

The owner's stated basis: every `full-*` item was checked against the cited official documentation (the Kafka 4.3 docs, the Airflow stable core-concepts pages and the other sources). The anchors, grades and relevance hold up, and the four unanswerable questions stay correctly unlabeled. The review did not say whether the completeness and paraphrase checks below were applied; those were applied when drafting. Every `full-*` line is now `"review": "reviewed"`. No other byte changed.

**Frozen SHA-256: `15c3bcb21f03a885f6c7878e2e2ab725636a277acb8757e279ff7c6de0b0162a`.** No search in any mode, bm25 and vector included, had been run on the new questions before the freeze. Labels were checked only with the dataset loader, the runner's label resolution and text search over the chunks. Calibration keeps using smoke only, so the 20 are the held-out check.

## How the 20 were drafted

- **Composition.** Four answerable questions per technology, each set with at least one identifier lookup and one how-to. Four unanswerable questions are inside the domain, one per technology; the smoke negatives are all other technologies. The new questions avoid the smoke topics, and two of them use documents smoke never labeled (the PostgreSQL SQL-language tutorial and the transaction-system text).
- **Anchors.** Every anchor resolves to exactly one current chunk. No two items of one question sit in the same chunk, because one chunk holding two items can never reach nDCG 1. Every label resolves, and none is flagged.
- **Completeness.** For each answerable question, the key terms were searched across all 20 public documents. Every passage that answers the question, or supports the answer, is labeled. The passages left out on purpose are listed below.
- **Paraphrase.** No question shares a run of four or more words with a labeled chunk, ignoring runs that include an identifier. Identifier questions still name their identifier, which favours BM25 as in smoke.
- **Negatives.** Each in-domain negative was chosen because its key terms are absent from every public chunk:

| Question | Term hits in the 816 public chunks |
|---|---|
| full-kafka-05 | tiered 0, remote.log 0, remote storage 0, MirrorMaker 0 |
| full-airflow-05 | secrets backend 0, vault 0; "secret" appears only in two Kafka OAuth settings |
| full-spark-05 | watermark 0, structured streaming 0 |
| full-postgresql-05 | pg_dump 0, pg_restore 0, dump 0; "restore" appears only in the Kafka design page and the WAL internals |

## The 20 questions

Grades as in smoke: 2 answers the question, 1 supports or answers part of it.

| Question | Type | Question text | Labeled passages (source: grade) |
|---|---|---|---|
| full-kafka-01 | identifier | With enable.idempotence switched on, what does the Kafka producer promise about retried sends, and is it on out of the box? | Producer configs, enable.idempotence: 2. Design, Message Delivery Semantics (idempotent delivery option): 1 |
| full-kafka-02 | how_to | How can I print every event already stored in a topic to my terminal, starting with the oldest one? | Quickstart Step 5 console consumer with `--from-beginning`: 2. Quickstart Step 6 console consumer on connect-test: 1 |
| full-kafka-03 | factual | If every in-sync replica of a partition fails, how does Kafka choose the next leader by default, and what does that trade away? | Design, unclean leader election ("By default from version 0.11.0.0..."): 2. The same section's first strategy: 1. Availability and Durability Guarantees, "Disable unclean leader election": 1 |
| full-kafka-04 | factual | Why do Kafka consumers request data from brokers instead of brokers sending it to them as it arrives? | Design, Push vs. pull (consumer falls behind and catches up): 2. The same section's batching advantage: 1 |
| full-kafka-05 | identifier | What does Kafka's remote.log.storage.system.enable setting switch on for tiered storage? | Unanswerable |
| full-airflow-01 | identifier | What does setting depends_on_past to True change for an Airflow task, and does it hold back the very first scheduled run? | Dags, Depends On Past: 2 |
| full-airflow-02 | how_to | How do I stop Airflow from parsing some of the files and folders in my Dag bundle? | Dags, .airflowignore: 2. Dags, Loading Dags paragraph introducing .airflowignore: 2 |
| full-airflow-03 | factual | What does Airflow do with a task instance that still shows as running although its worker has crashed? | Tasks, Task Instance Heartbeat Timeout: 2 |
| full-airflow-04 | factual | When a @task.branch function returns one task ID, what happens to the downstream tasks it did not choose? | Dags, Branching ("all other paths are skipped"): 2. The same section's join example: 1 |
| full-airflow-05 | how_to | How do I configure Airflow to read its connections and variables from HashiCorp Vault as a secrets backend? | Unanswerable |
| full-spark-01 | identifier | What does spark.sql.sources.default decide in Spark SQL, and what value does it fall back to? | Generic Load/Save Functions (parquet default): 2 |
| full-spark-02 | how_to | How do I run an application through spark-submit on just my own machine, using every logical core? | Submitting Applications, Master URLs `local[*]`: 2. The same page's "Run application locally on 8 cores" example: 1 |
| full-spark-03 | factual | What fraction of a machine's RAM should Spark be allowed to use, and what is the remainder for? | Hardware Provisioning, Memory (at most 75%): 2 |
| full-spark-04 | factual | How many tasks should each CPU core in a Spark cluster get, and which property changes the default parallelism? | Tuning, Level of Parallelism: 2 |
| full-spark-05 | factual | How does a watermark limit how late events may arrive in a Spark Structured Streaming aggregation? | Unanswerable |
| full-postgresql-01 | identifier | What does PostgreSQL record in pg_xact, and which states can a transaction have there? | Transaction system, pg_xact commit status: 2. The same section's on-disk storage sentence: 1 |
| full-postgresql-02 | how_to | How can I bulk-load rows into a table from a text file instead of writing INSERT statements, and which machine must hold the file? | SQL-language tutorial 2.4, COPY: 2 |
| full-postgresql-03 | factual | Under Repeatable Read, what happens when my transaction tries to change a row that another transaction modified and committed after mine began? | Transaction Isolation 13.2.2 (cannot modify rows changed after it began): 2. The same section's wait for the first updater: 1 |
| full-postgresql-04 | factual | How does a window function differ from an ordinary aggregate such as avg() used with GROUP BY? | Advanced-features tutorial 3.5 (rows are not grouped): 2. Access beyond the current row: 1. The OVER clause turning avg into a window function: 1 |
| full-postgresql-05 | how_to | How do I back up a single PostgreSQL database with pg_dump and restore it on another server? | Unanswerable |

## What the reviewer checks

The four checks for answerable questions in the smoke section above apply here as well. For each in-domain negative, confirm that nothing in the 20 public documents answers it, even though it is about one of the four technologies.

To accept a question, change its `draft` to `reviewed`. To change one, edit it and log the disagreement below. Either edit changes the dataset hash, which is intended. Any later change makes a new dataset version, which needs its own review.

## Points for the reviewer

| Question | Point |
|---|---|
| full-kafka-01 | The default ("Default: true", "enabled by default if no conflicting configurations are set") is in the same chunk as the grade 2 anchor. The acks, retries and max.in.flight entries mention idempotence only as a constraint, so they are not labeled. |
| full-kafka-03 | Three passages in two sections. The grade 2 sentence says "the first strategy", which only the grade 1 passage before it defines. |
| full-kafka-05 | An identifier negative: its tokens (remote, log, storage, enable) match many producer-config chunks, which makes it a hard negative for BM25. |
| full-airflow-02 | Two grade 2 passages: either one alone tells you to use `.airflowignore`. |
| full-airflow-03 | This is the same chunk that makes smoke-ood-03 (Kubernetes liveness probes) a hard negative. |
| full-airflow-04 | The tasks page lists the `skipped` state "due to branching" but does not say which tasks are skipped, so it is not labeled. |
| full-airflow-05 | The architecture overview names "Connections & Hooks" in one sentence but never explains secrets backends. |
| full-spark-02 | The grade 1 example uses `local[8]`, not `local[*]`; it shows the `--master` flag in a full spark-submit command. |
| full-postgresql-01 | The source is PostgreSQL's transaction-system README, written for developers. It is the only document in the corpus that covers pg_xact. |
| full-postgresql-03 | The error text "could not serialize access due to concurrent update" is in the grade 2 chunk. The Serializable section's different error is not labeled. |
| All | The questions were written after reading the passages. The four-word check limits copied wording but does not remove the bias toward BM25. |

## Disagreements

| Date | Question | Reviewer's position | Resolution |
|---|---|---|---|
| 2026-11-13 | All 20 `full-*` | Accepted as drafted, checked against the cited official documentation | No change |
