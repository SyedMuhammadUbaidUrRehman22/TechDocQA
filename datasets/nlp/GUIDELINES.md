# Phase 9 annotation guidelines

These guidelines cover the three gold sets that Phase 9 scores (P9-9): entities (AC-07.4), key terms (AC-08.3) and sentence boundaries (AC-06.4). They were written on 2026-11-07, before any labels.

**Revised 2026-11-12, before round 2 was labeled.** The round-1 annotators decided several unclear cases and recorded them in `review_log.md`. Those decisions are now written into the rules below, marked *(round 1)*, so round 2 follows the same conventions. No rule was dropped, and the definitions of a key term and of each entity type are unchanged apart from the wording noted in the type table.

**Label from the text alone.** The sheets never show extractor output, and you should not run `enrich` or look at the gazetteer while labeling. Label what a reader of the page would call an entity or a key term, not what you expect a rule to find. If a case is unclear, decide it, write a line under `Notes:`, and apply the same decision every time.

## Where the files are

`python datasets/nlp_gold.py sheets` writes the sheets into `data/nlp/`, which git ignores because the sheets hold document text:

| Sheet | You fill in |
|---|---|
| `entities_sheet.md` | The `labels` block under each of the 20 chunks |
| `keyterms_sheet.md` | The `terms` block for each of the 5 documents; their text is in `data/nlp/keyterms/` |
| `segmentation_sheet.md` | Claude Code drafted the boundaries; you review them |

`python datasets/nlp_gold.py freeze --reviewer NAME` then checks the sheets and writes `datasets/nlp/*_gold.jsonl`, which hold positions, hashes, short anchors and labels but no chunk text. It refuses to freeze the entity set if the gazetteer changed after sampling.

Round 2 uses the same commands with `--round 2`: the sheets go to `data/nlp/round2/` (32 entity chunks and 15 key-term documents, no sentence sheet) and the gold files to `datasets/nlp/round2/`. While labeling round 2, do not open the round-1 sheets or gold files either.

## How the samples were drawn

All samples come from the public reference and never from DDIA. Order comes from SHA-256 of a fixed seed and the text, so anyone rerunning `sheets` on the same corpus gets the same samples.

- **Entities:** 5 chunks per technology, at least 400 characters each, at most 2 per document. The first chunk for each technology is drawn from chunks where an ambiguous name such as Kafka, Spark or Airflow appears in a different case or inside a longer technical token (`kafka-topics.sh`). That gives at least 4 such chunks in the 20; the sampler found 6. Which chunks those are is not shown.
- **Key terms:** for each technology, the document with the fewest chunks among those with 30 or fewer, then the smallest document in a format not yet covered. That gives 4 technologies and 3 formats (HTML, Markdown, PDF).
- **Sentences:** 5 whole prose paragraphs per technology, at most 2 per document, outside the entity chunks. Draws alternate between paragraphs with a hard case (abbreviation, dotted name, version number, ellipsis, colon) and plain ones.
- **Round 2 (2026-11-12):** a new seed, drawn after the extractor was revised on round 1. Entities: 8 chunks per technology by the same rule, none overlapping a round-1 entity chunk or sentence passage. Key terms: every evaluation document not in round 1, 15 in all and of any length, so none is chosen by hand.

## Entities (AC-07.4)

Write one mention per line in the `labels` block, as `TYPE | exact text`, copying the text exactly as it appears in the chunk, including its case. For example:

```text
TECHNOLOGY | Apache Kafka
IDENTIFIER | linger.ms
CONCEPT | consumer group
```

### Types

| Type | What it is | Examples |
|---|---|---|
| `TECHNOLOGY` | A named product, project, language, platform or library | Apache Kafka, PostgreSQL, Python, Jinja, Kubernetes, HDFS |
| `COMPONENT` | A named part of a technology that runs: a server role, process, subsystem or built-in service. A tool you run by name, such as `spark-submit`, is an `IDENTIFIER` | broker, scheduler, executor, driver, WAL writer, Kafka Connect, the query planner |
| `CONCEPT` | A technical idea specific to the field, usually a noun phrase with a fixed meaning, including a named kind of object that users define or choose *(round 1)* | partition, consumer group, Dag run, serializable isolation, MVCC, B-tree index; Airflow's Task, Operator, Sensor, XCom and Dag; PostgreSQL index types (GIN, GiST, SP-GiST) and plan nodes (Sort, Limit) |
| `PROTOCOL` | A network, wire, security or data-exchange protocol | HTTP, HTTP/2, TLS, SASL, JDBC, gRPC |
| `IDENTIFIER` | A name you would type: a configuration key, command, function, class, file, flag or code symbol | `linger.ms`, `spark-submit`, `--deploy-mode`, `pg_subtrans`, `AirflowTaskTimeout`, `BeginInternalSubTransaction` |

### Rules

1. **Longest whole mention.** Label `kafka-topics.sh` as one `IDENTIFIER`, not `kafka` inside it. Label `Apache Kafka` once, not also `Kafka`. Label `consumer group`, not also `consumer`.
2. **Ambiguous names count only as the technology.** `Kafka` in "Kafka brokers replicate data" is a `TECHNOLOGY`. A lowercase `spark` meaning a small flash, Kafka the author, or `airflow` meaning moving air are not entities. A name inside an identifier follows rule 1.
3. **Each distinct mention once per chunk.** If `partition` appears five times, write it once. Scoring compares the set of (chunk, normalized text, type) per chunk. Normalized means NFKC, case-folded, with whitespace collapsed, so `Partition` and `partition` are the same mention. Write the form that appears first.
4. **Singular and plural are different texts.** If only `partitions` appears, write `partitions`. If both forms appear, write both.
5. **Concepts must be technical.** Do not label generic words such as data, system, user, value, time, file or example, even when they carry the topic. Label `data interval` and `log compaction`, but not `data` or `log`. Spark's bare `task` and `job` are generic words *(round 1)*.
6. **Not entities:** version numbers (`3.8.18`), URLs, ports and plain numbers, abbreviations (`e.g.`), people, companies that are not products, and whole code statements. A function name inside code counts as an `IDENTIFIER`. `IoT` and operator symbols are not entities *(round 1)*.
7. **Identifiers need a typed form.** Dotted, snake_case, CamelCase, flags, commands and file names count. An ordinary capitalized word does not count unless the text uses it as a code name. Code names that are not dictionary words count (`mytab`, `tenk1`); ordinary words used as column names do not (`name`, `value`) *(round 1)*.
8. **SQL keywords** such as `SELECT`, `EXPLAIN ANALYZE` and `IS NULL` are `IDENTIFIER` when the text uses them as syntax. Split a statement into its syntactic units: `CREATE TABLE`, `ORDER BY`, `SELECT`, each once per chunk *(round 1)*.
9. **Chunks with no entity** keep an empty `labels` block.
10. **A command or file given with a directory** is labeled by its name: `kafka-topics.sh`, not `bin/kafka-topics.sh` *(round 1)*.

## Key terms (AC-08.3)

For each document, read its text and list **10 to 15 key terms** in the `terms` block, one per line, most important first. A key term is a word or phrase of 1 to 4 words that someone would use to find this document or summarize what it teaches.

- Copy terms as they appear in the text, so they can match exactly. Case does not matter. A term that never appears in the text cannot be matched.
- Prefer the document's main subjects (`log compaction`, `consumer group`) over incidental words (`example`, `following`).
- Technical identifiers count when they are central (`linger.ms` in a page about producer settings).
- Do not list the technology name alone, such as `Kafka` in a Kafka page, because it is true of every page.
- Do not list the same term in two forms. Pick the form used most often (`Dag`, `tasks`, `topic`) *(round 1)*.
- The page title counts where it names the subject (`Hardware Provisioning`, `Getting Started`); names invented for an example (`mydb`) do not *(round 1)*.
- A long document gets 10 to 15 terms for the whole document, not for one section.

Scoring checks how many of your terms appear among the extractor's top 10 by normalized exact match. A lenient match, where one contains the other, is reported only as a diagnostic.

## Sentence boundaries (AC-06.4)

Each `sentences` block is one whole paragraph with a `‖` mark after every sentence except the last. Claude Code drafted the marks with a simple splitter that is not the segmenter under test: a mark after `.`, `!` or `?` that is followed by whitespace and then a capital letter or a quote. Claude Code then corrected the draft by hand. Review every mark:

- Add, move or delete marks. Never change any other character, or `freeze` refuses the sheet.
- Whitespace next to a mark belongs to neither sentence, so a mark may sit before or after a line break.
- A sentence ends at its final punctuation, including a closing parenthesis or quote: `…these operators.)‖ The GIN…`.
- Line breaks from hard-wrapped text are not boundaries.
- Abbreviations (`e.g.`, `i.e.`, `etc.` mid-sentence), dotted names (`min.cleanable.dirty.ratio`), file extensions (`.zip`), version numbers and an ellipsis inside a quoted statement (`SELECT ... WHERE`) are not boundaries.
- In a flattened list, each item is a sentence even without end punctuation.

Scoring compares the exact positions of every sentence start and end with the segmenter's, as boundary F1 over 50 or more sentences.

## What the scores mean

The sets are small (round 1: 20 chunks, 5 documents, about 66 sentences; round 2: 32 chunks, 15 documents). Every figure is reported with its denominator and a Wilson 95% interval, and split by technology and format, with each error listed. A target met only at the point estimate is reported that way, and all results are labeled indicative (VULN-04).
