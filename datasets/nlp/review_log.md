# Phase 9 gold data review log

The gold sets are scored by `eval --enrichment` (P9-9): [segmentation](segmentation_gold.jsonl) (AC-06.4), [entities](entities_gold.jsonl) (AC-07.4) and [key terms](keyphrases_gold.jsonl) (AC-08.3). Labels follow the [guidelines](GUIDELINES.md). The corpus is the frozen public reference `techdocqa-reference-2026-10-24-v2`. DDIA is never sampled.

## Status

**Sheets written 2026-11-07; awaiting annotation.** Nothing is frozen yet.

| Set | Size | Who | State |
|---|---|---|---|
| Entities | 20 chunks, 5 per technology; 6 in the ambiguous-name stratum | Project owner labels | Awaiting labels |
| Key terms | 5 documents: Airflow HTML (21 chunks), Kafka HTML (18), Spark Markdown (9), PostgreSQL HTML (15), PostgreSQL PDF (18) | Project owner labels | Awaiting labels |
| Sentences | 20 paragraphs, 66 drafted sentences | Claude Code drafted; project owner reviews | Awaiting review |

At sampling, the gazetteer SHA-256 was `058dc8a88a694de9673d876e71d2b1c1d68145522c06cd55bc14535e694c9d64` and the manifest SHA-256 was `26eb4adc4483636b71ac0cd1e19bcd63cbfd8fca95360e9b4b790c883ddc4bf9`. The gazetteer is now frozen: `freeze` refuses the entity set if this hash changes.

## How the sentence draft was made

A naive splitter marked a boundary after `.`, `!` or `?` followed by whitespace and a capital letter or quote, which gave 63 boundaries. Claude Code read all 20 paragraphs and changed three:

- **S17:** added a boundary after `…these operators.)`. The splitter missed it because a parenthesis follows the period.
- **S15:** added boundaries after `…driver HTTP server.` and after `…as expected`, where Spark's flattened list of URI schemes puts each item on its own line, one of them without end punctuation.

The other drafted boundaries were checked and kept, including the cases that are not boundaries: `i.e.` (S05, S10), `e.g.` (S16), dotted names (S07, S11, S18), `etc.` at the end of S15 and the `{{ context.params }}` template in S01.

## Reviews

Each `freeze` appends an entry below with the reviewer, the date and the SHA-256 of each gold file.
