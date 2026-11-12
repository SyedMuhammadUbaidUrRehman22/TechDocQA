# Phase 9 gold data review log

The gold sets are scored by `eval --enrichment` (P9-9): [segmentation](segmentation_gold.jsonl) (AC-06.4), [entities](entities_gold.jsonl) (AC-07.4) and [key terms](keyphrases_gold.jsonl) (AC-08.3). Labels follow the [guidelines](GUIDELINES.md). The corpus is the frozen public reference `techdocqa-reference-2026-10-24-v2`. DDIA is never sampled.

## Status

**Frozen 2026-11-12.** The sheets were written on 2026-11-07. The project owner then designated Fable 5.1, an AI model, to label the entity and key-term sets and to review the sentence draft, in place of the owner. The owner approved this on 2026-11-12 as a recorded deviation from the plan ([decisions](../../docs/DECISIONS.md#phase-9-completion-2026-11-12)), so the scores measure agreement with an AI annotator, not human ground truth.

| Set | Size | Who | State |
|---|---|---|---|
| Entities | 20 chunks, 5 per technology; 6 in the ambiguous-name stratum; 165 mentions | Fable 5.1 labeled | Frozen |
| Key terms | 5 documents: Airflow HTML (21 chunks), Kafka HTML (18), Spark Markdown (9), PostgreSQL HTML (15), PostgreSQL PDF (18); 72 terms | Fable 5.1 labeled | Frozen |
| Sentences | 20 paragraphs, 66 sentences | Claude Code drafted; Fable 5.1 reviewed and changed nothing | Frozen |

At sampling, the gazetteer SHA-256 was `058dc8a88a694de9673d876e71d2b1c1d68145522c06cd55bc14535e694c9d64` and the manifest SHA-256 was `26eb4adc4483636b71ac0cd1e19bcd63cbfd8fca95360e9b4b790c883ddc4bf9`. The gazetteer is now frozen: `freeze` refuses the entity set if this hash changes.

## Out-of-topic fixtures (2026-11-12)

[out_of_topic.jsonl](out_of_topic.jsonl) holds the 10 texts for the FR-09 `unclassified` threshold (P9-6, AC-09.2). They are not gold labels and need no annotation. Claude Code wrote them before any measurement and fixed the split in the file: 5 for calibration (gardening, chess, a household budget, CSS layout, Git branches) and 5 held out (the cooking article, garden birds, bicycle brakes, home Wi-Fi, LaTeX). Four of the ten are technical but outside the four configured categories. SHA-256 `e8180839ea52c2af552172ca773049f778f02b18f00fc2ad2e4a2b280b91a71f`. `eval --enrichment` reads them in memory and writes nothing.

Since 2026-11-12, `freeze` also writes the gazetteer hash at sampling into every entity row, so `eval --enrichment` can report a later gazetteer change as tuned.

## How the sentence draft was made

A naive splitter marked a boundary after `.`, `!` or `?` followed by whitespace and a capital letter or quote, which gave 63 boundaries. Claude Code read all 20 paragraphs and changed three:

- **S17:** added a boundary after `…these operators.)`. The splitter missed it because a parenthesis follows the period.
- **S15:** added boundaries after `…driver HTTP server.` and after `…as expected`, where Spark's flattened list of URI schemes puts each item on its own line, one of them without end punctuation.

The other drafted boundaries were checked and kept, including the cases that are not boundaries: `i.e.` (S05, S10), `e.g.` (S16), dotted names (S07, S11, S18), `etc.` at the end of S15 and the `{{ context.params }}` template in S01.

## How the labels were made (2026-11-12)

Claude Code started three separate Fable 5.1 sessions, one per set. Each was told to read only the guidelines and its own sheet (for key terms, also the five document texts). None was to open the code, the gazetteer, `sample.json`, this log or any report, or to run a command. Claude Code checked what came back before freezing: every entity label is an exact substring of its chunk, every key term appears in its document, and the sentence sheet is byte-identical to the draft. No label was changed after a score was seen.

Decisions the annotators recorded and applied throughout:

- **Entities:** a command or file is labeled by its name without the directory (`kafka-topics.sh`, not `bin/kafka-topics.sh`). Airflow's Task, Operator, Sensor, XCom and Dag are `CONCEPT`; Spark's bare `task` and `job` are generic. PostgreSQL index types (GIN, GiST, SP-GiST) and plan nodes (Sort, Limit, Incremental Sort) are `CONCEPT`. SQL keywords are split into syntactic units (`CREATE TABLE`, `ORDER BY`, `SELECT`). Code names that are not dictionary words are identifiers (`mytab`, `tenk1`); ordinary words used as column names are not (`name`, `value`). `IoT`, URLs and operator symbols are not entities.
- **Key terms:** the form used most often (`Dag`, `tasks`, `topic`); the page title where it names the subject (`Hardware Provisioning`, `Getting Started`); no example names (`mydb`).
- **Sentences:** the unpunctuated item in S15's flattened list ends a sentence, and an item holding two full sentences is two sentences.

`freeze` ran three times on these labels. The first two runs wrote the gold files with CRLF line endings on Windows, so the hashes they logged would not match a checkout; their log entries were removed. `freeze` now always writes LF, and the entry below is from that run.

## Round 1 as development data (2026-11-13)

After round 1 was scored, entity rules v2, a gazetteer revision and the `technical-ngrams-v1` keyphrase policy were made while looking at its labels, under the implementation task the owner approved on 2026-11-12. Round 1 is therefore development data: `eval --enrichment` reports a new entity or n-gram key-term score on it as tuned, and such a score is not evidence for AC-07.4 or AC-08.3. The guidelines were revised the same day only to write down the conventions recorded above. The held-out test is round 2 (`nlp_gold.py --round 2`), drawn after the code is frozen; its plan and freeze are logged below.

## Reviews

Each `freeze` appends an entry below with the reviewer, the date and the SHA-256 of each gold file.

## Frozen 2026-11-12 by Fable 5.1 (AI annotator designated by the project owner)

- Seed `techdocqa-nlp-gold-2026-11-07`; manifest SHA-256 `26eb4adc4483636b71ac0cd1e19bcd63cbfd8fca95360e9b4b790c883ddc4bf9`
- Gazetteer SHA-256 at sampling `058dc8a88a694de9673d876e71d2b1c1d68145522c06cd55bc14535e694c9d64`
- `segmentation_gold.jsonl` SHA-256 `fd4aaf641fdd0648957de4c6df972f5e5160a0477263aaa890605343bb551294`
- `entities_gold.jsonl` SHA-256 `b82e2f094e1a86546482a82f06511b600270ee3103e5a4eda4837c5b14578bc4`
- `keyphrases_gold.jsonl` SHA-256 `320534b487f0c12bff22f2fbe050d13016de6c5e7609e1a8df1bbebdab7ed88d`

## Round 2: plan fixed before sampling (2026-11-13)

The owner made the AC-07.4 and AC-08.3 improvements a separate implementation task on 2026-11-12 and asked for a fresh blind sample for each. Round 1 is development data (above). Round 2 is the held-out test. This plan was written and committed before the round-2 sample was drawn and before any round-2 label existed.

- **Frozen code.** Entity rules `techdocqa-entity-rules-v2`, gazetteer `techdocqa-gazetteer-2026-11-12` (SHA-256 `7aa9d0f725d871e49a129539ee85a72f9f50c5a69f4d5f697b764de0c52e8744`) and keyphrase policy `technical-ngrams-v1` with code blocks, as committed in `3e48ab8`. Nothing in them changes between sampling and scoring. The only later code change, committed with this plan, is in the evaluator: a verdict on tuned data is now printed as such.
- **Sample.** `nlp_gold.py --round 2 sheets`, seed `techdocqa-nlp-gold-round2-2026-11-12`. Entities: 8 chunks per technology (32), by the round-1 rule, none overlapping a round-1 entity chunk or sentence passage. Key terms: all 15 evaluation documents not in round 1, of any length. No sentence set: the segmenter was not tuned, and AC-06.4 stands on round 1.
- **Guidelines.** Revised before sampling only to write down the conventions the round-1 annotators recorded, marked *(round 1)*. The definitions of a key term (1 to 4 words, 10 to 15 per document) and of each entity type are otherwise unchanged.
- **Annotator (deviation).** The owner approved Fable 5.1 as the annotator for round 1. On 2026-11-13 Fable 5.1 can no longer be selected: the only Fable model offered to Claude Code reports itself as `claude-fable-5-2`. Fable 5.2 is the model the owner first asked for on 2026-11-12, when it was not available. Round 2 is therefore labeled by Fable 5.2. This departs from the approved annotator, and the owner has not yet confirmed it. If the owner prefers another annotator, the same frozen sample can be labeled again, because the extractor does not change.
- **Blind labeling.** Four separate sessions, one for entities and three for key terms (Airflow and Spark; Kafka; PostgreSQL). Each sees only the guidelines, its sheet and its key-term texts: no extractor output, code, gazetteer, sample file, review log, report, or round-1 sheet or gold file. Claude Code, which coordinates on Fable 5.2 in a separate session, checks that every label is an exact substring and freezes the labels unchanged.
- **Scoring.** One run of `eval --enrichment --gold-dir datasets/nlp/round2 --fixtures datasets/nlp/out_of_topic.jsonl`. AC-07.4 on verified mentions, micro-averaged over the 32 chunks. AC-08.3 on the configured variant `ngram/with_code`, as the mean over all 15 documents. The split at 30 chunks, round 1's size limit, is a secondary figure, not a verdict. Verdicts follow the existing rules (Wilson 95% lower bound). The result is reported as measured, whatever it is, and no rule, word list or setting is changed after it is seen.
- **What the score means.** Agreement with an AI annotator, not human ground truth, and with a different model from round 1's annotator.
