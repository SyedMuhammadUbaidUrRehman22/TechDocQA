# Phase 9 plan: P1 NLP enrichment

Status: **proposed 2026-11-04, revised 2026-11-07 after the [risk assessment](#risk-assessment-2026-11-07), approved 2026-11-07; implemented and measured 2026-11-12; AC-07.4 and AC-08.3 are recorded as not met (owner decision 2026-11-12); their improvements are built as a separate task and await the held-out round-2 measurement.** P9-1 to P9-12 are recorded as [Phase 9 contracts](DECISIONS.md#phase-9-contracts-2026-11-07), with YAKE replaced by RAKE at the dependency gate, and the implementation as [Phase 9 completion](DECISIONS.md#phase-9-completion-2026-11-12). See [Progress](#progress-2026-11-12) and the [Phase 9 report](PHASE_9_STATUS.md). It covers roadmap Phase 9: FR-06 full, FR-07, FR-08, FR-09 and their FR-12/FR-13 filter extensions. Sources: [Revision 3 requirements](../TechDocQA_Requirements_v2.md), [roadmap](IMPLEMENTATION_ROADMAP.md#phase-9--p1-nlp-enrichment), [decisions](DECISIONS.md) D-08, Q-11, Q-14 and Q-16, and the [Phase 8 report](PHASE_8_STATUS.md).

## Entry gate

The roadmap puts Phase 9 after the P0 release gate. That gate passed on 2026-11-07: AC-16.6 was rated 8 of 10 by the designated reviewer, AC-12.1 is met as amended, and Q-07, Q-12 and Q-13 are approved ([approvals](DECISIONS.md#p0-approvals-2026-11-07)).

## Invariants

Phase 9 adds filters that intentionally change the results of filtered queries, so "no change to retrieval" holds only for what existed before. There are two separate invariants:

1. **Existing behavior is unchanged.** Unfiltered retrieval, and `--category` on any document with a user category, give the same results before and after `enrich`. Two checks prove it:
   - The smoke `eval` gives the same `results_fingerprint` as the baseline run `eval_50d06f55b10541ccbccc0ef6d77abb9d` (metric policy `q13-v1`). That fingerprint hashes the dataset, the corpus identity (version, content hash, chunking configuration and snapshot hash per document), the metric policy and every question's ranked results. Its searches are unfiltered and scoped by source key. It deliberately excludes enrichment tables, so enrichment cannot change it except by changing retrieval.
   - `datasets/verify_index.py --compare` reproduces the stored top-5 snapshot of its fixed queries.

   The QA prompt does not read enrichment data. A test checks that prompt hashes are identical with and without enrichment rows, so the Phase 8 calibration and answers stay valid.
2. **New filter behavior passes its own criteria.** `--entity` with extracted entities and `--category` with inferred categories are judged by AC-07.3, AC-09.3 and the P9-7 rules, not by the fingerprint. Before `enrich`, the only document whose category matching changes is DDIA, which has no user category.

## What already exists

| Piece | State | Use in Phase 9 |
|---|---|---|
| FR-06 P0 sentence spans | `technical-sentences-v4`, stored per chunk artifact; part of `chunking_config_id` | Baseline for AC-06.4. Changing the segmenter used for chunking re-chunks everything. |
| Chunk provenance | Exact source offsets, section paths and pages per chunk | Entity offsets can be chunk-relative and mapped to document offsets. |
| Entity filter (Q-16 P0 slice) | `verified_entities` table and `--entity` in both retrievers, gated by eligibility; **0 rows** | FR-07 fills it; no search change needed. |
| Category filter | `--category` matches the single user-supplied category; all 20 public documents have one from ingestion, DDIA has none | FR-09 adds inferred categories. A user category keeps precedence (FR-09.4). |
| Stored chunk vectors | 2,727 vectors in the registry | Embedding-based classification needs no new document embeddings. |
| BM25 technical tokenizer | Keeps dotted names, `snake_case`, `--flags`, `C++` | Reuse its patterns for `IDENTIFIER` extraction, so both see the same tokens. |
| Evaluation runner | Manifest scope, stable anchors, reports, fingerprints | Pattern for the enrichment report and its gold sets. |

## Acceptance targets

The numeric targets stay as written until an approved amendment (Q-14), including the three that Appendix C asks to confirm.

| Criterion | Target | Planned evidence | Data needed |
|---|---|---|---|
| AC-06.4 | Boundary F1 ≥ 0.95 on 50 annotated sentences | `eval --enrichment` and a test, for P0 rules and the spaCy segmenter | 50-sentence gold set |
| AC-07.1 | 5 named entities, correct types | Test fixture | Synthetic text |
| AC-07.2 | Every entity has valid chunk and document IDs | Test, plus a real-corpus check | none |
| AC-07.3 | `entity=Redis` returns only verified Redis chunks | Test fixture (no Redis in corpus); real check with `entity=PostgreSQL` | none |
| AC-07.4 | Precision ≥ 0.80, recall ≥ 0.60 on ≥ 20 labeled chunks | `eval --enrichment` on the real corpus | Entity gold set |
| AC-08.1, AC-08.2 | 1 to N phrases in descending score; one-word chunk gives an empty list | Tests and real corpus | none |
| AC-08.3 | ≥ 50% of annotated key terms in the top 10, mean over 5 documents | `eval --enrichment` | Key-term gold set |
| AC-09.1 | Accuracy ≥ 0.85 on ≥ 2 documents per configured category | `eval --enrichment` on all 20 public documents | Manifest categories as labels |
| AC-09.2 | Out-of-topic document gets `unclassified` | Test with the fake embedder; real-model check on fixture texts | 10 out-of-topic fixtures, the cooking article among them: 5 to calibrate the threshold, 5 held out (P9-6) |
| AC-09.3 | `category=Caching` returns no other category | Test fixture; real check with `category=Databases` | none |

## Decisions to approve before coding

| ID | Decision | Recommendation | Why, and the alternative |
|---|---|---|---|
| P9-1 | Libraries (D-08) | **spaCy 3.8.18** for FR-06 P1 (MIT; Windows wheel for Python 3.13 on PyPI). **YAKE 0.7.3** for FR-08 (pure Python, **LGPLv3**). No KeyBERT, torch or LLM extraction. Both must pass the dependency gate in step 1. | spaCy is the requirement's own example. YAKE is light and deterministic, and its lower-is-better score maps to a descending score. Alternative: RAKE (`rake-nltk`, MIT), which needs NLTK and a stop-word download. |
| P9-2 | Segmenter adoption | Measure P0 rules, the spaCy `sentencizer` with technical rules, and, if needed, the `senter` from `en_core_web_sm` 3.8.0 on the same gold set. Make spaCy a selectable segmentation policy. Use it for chunking only if it beats the rules and you accept the rerun. | Chunking under a new policy means re-chunking 21 documents, re-indexing (548 s last time), rerunning `eval` and reviewing the Phase 8 threshold proposals. Keeping chunking on P0 rules leaves every Phase 5 to 8 result intact. |
| P9-3 | Entity extractor | A gazetteer in `config/gazetteer.toml`: canonical name, aliases, type, an optional technology-to-category link and an `ambiguous` flag. Regex patterns cover `IDENTIFIER` and `PROTOCOL`. **An exact gazetteer match** (FR-07.2: confidence 1.0) is a match on an unambiguous alias with its configured case. An ambiguous alias (`Spark`, `Airflow`, `Kafka`) is exact only when its entry's context rule holds: the qualified form (`Apache Spark`), or an exact-case match in a document whose user technology is that entity. Otherwise it is stored as a candidate at 0.4, so `verified=false` (Appendix A threshold 0.5) and it never feeds a filter. Regex patterns get fixed confidences below 1.0. A gazetteer match inside a longer `IDENTIFIER` (`kafka-topics.sh`, `spark.memory.fraction`) is not a separate mention: the longest match wins and overlapping matches are dropped. Every entity stores `rule_id` and its matched surface as evidence. Confidence is a rule-assigned level, not a probability; the gold set measures precision. No model-based extractor. | FR-07 requires rules. A regex matcher keeps technical tokens whole, where spaCy's tokenizer would split `linger.ms`. The context rule addresses false verification (VULN-01) without changing FR-07.2's definition. |
| P9-4 | Offsets (Q-11) | Half-open character offsets into the chunk text, plus offsets into the **normalized** Document or page text: the chunk's source start plus the chunk offset, with that Document's index. This is exact because chunk text is an unaltered substring of the normalized text (Q-10/Q-11, checked by `verify_corpus.py`). Offsets into raw HTML or PDF bytes are not provided: decoding, cleaning and NFC normalization make them many-to-one. A write-time check rejects any entity whose normalized-text slice differs from its stored text. Tests cover NFC text, decoded HTML entities, collapsed whitespace, CRLF input and multi-page PDFs. | Chunk offsets are what search returns; normalized offsets survive display. Naming the reference text settles VULN-05. |
| P9-5 | Keyphrases | Top 10 per document, stored with rank, a descending `score` and the raw YAKE value. Per-chunk keyphrases are configurable and off by default. Whether code blocks count is decided by measurement on the gold set. Keyphrases do **not** enter BM25 text. | Adding them to BM25 would change its score scale, make the BM25 thresholds stale and double-count chunk words. Phase 10 can measure that with hybrid search. |
| P9-6 | Classifier | **Embedding similarity** as the default, fully specified: (1) each configured category description is embedded once, using the embedding profile's query prefix; (2) the document vector is the L2-normalized mean of the stored vectors of the document's current chunks, one per chunk occurrence; (3) each category's score is the cosine between the two, rounded to 6 places; (4) categories are ranked by score, ties broken by category name, and up to 3 at or above the `unclassified` threshold are kept; none left means `unclassified`. The stored field is FR-09.2's `confidence`, but it is a **similarity score, not a probability**, and every record carries `similarity_policy`, the classifier configuration ID and the threshold's calibration run ID. Threshold: 10 out-of-topic fixtures, 5 for calibration and 5 held out (the cooking article among them, for AC-09.2), plus the 20 public documents with leave-one-document-out errors reported. The in-topic side is not independent of the AC-09.1 assessment, which the report states. A rule baseline, technology entities mapped to categories, is reported beside it. The classifier never reads the user-supplied technology or category. | It generalizes beyond named technologies and uses the framework embedder with no new document calls. Rules alone would score near 100% here, because each document names its technology, which says little. The category descriptions are written and frozen before the first measurement. Alternatives: rules as default, or a zero-shot `qwen3:1.7b` prompt, which is slower and less deterministic. |
| P9-7 | Category filter (Q-16) | A document matches `category=X` when X is its user category; without one, when X is among its inferred categories at or above the threshold. `category=unclassified` is a valid filter. The Chroma `category` field keeps the registration value, and the registry decides filters, as it does today. | This keeps a single registry decision for both retrievers and AC-02.5 unchanged. The alternative, matching only the top inferred category, loses the multi-category behavior FR-09.2 asks for. |
| P9-8 | Storage | Registry schema version 3, additive, with new tables `entities` (all, with `verified`), `keyphrases` and `document_categories`. **Migration:** one `BEGIN IMMEDIATE` transaction holds the write lock from before the backup until the migration commits, so nothing can commit in between and a concurrent opener waits, then finds version 3. Inside it, first a copy through SQLite's backup API to `registry.sqlite3.pre-v3.bak`, created exclusively (an existing backup is never overwritten; the next free `.pre-v3.N.bak` is used). The copy is opened and must pass `integrity_check` with row counts equal to the live registry. Then v2 to v3 runs in the same transaction, as v1 to v2 does today, so an interrupted migration leaves version 2 intact. **Writes:** `enrich` holds the registration lock that `ingest`, `chunk`, `index`, `withdraw` and `delete` already take, so no re-chunk or deletion runs concurrently (`REGISTRY_BUSY`). Each document's results are computed first, then written in one transaction that deletes the version's old rows and inserts the new ones, including `verified_entities`. Rows carry the version ID, `chunking_config_id`, the chunk snapshot hash and an `enrichment_config_id`. Readers ignore rows whose identity does not match the active artifact, so stale rows never filter results, even before the next `enrich` replaces them. Unchanged identities are skipped, so reruns are idempotent. A new run stage is `enrichment`; there is no new processing status (Q-02). | Per-document and per-chunk queries need SQL. Tests: a failure injected mid-document leaves that document's rows unchanged; a failure injected mid-migration leaves `user_version = 2` and the v2 schema; a restore from the backup reopens with equal counts; a second `enrich` during a run gets `REGISTRY_BUSY`; re-chunking makes old rows invisible (VULN-07). |
| P9-9 | Gold data and metrics | You annotate the entity and key-term sets **before** seeing extractor output; Claude Code prepares sheets and guidelines and drafts the segmentation set for your review. Chunks are sampled by a fixed rule, 5 per technology from the public reference, never DDIA. At least 4 of the 20 chunks contain an ambiguous name used as a non-entity or inside an identifier. The gazetteer is frozen and hashed before the entity set is scored; a later change needs a fresh sample or is reported as tuned. Committed gold files hold source keys, short anchors and labels, not whole chunks. | This avoids Phase 8's calibration-and-assessment overlap. Metric rules: boundary F1 on exact positions; entity precision and recall on (chunk, normalized text, type) mentions, micro-averaged and also per type; key-term hits on normalized exact match, with a lenient match reported only as a diagnostic; classification on top-1 against manifest labels, with a confusion matrix. Every figure is reported with its denominator and a Wilson 95% interval, split by technology and format, with each error listed. Results are labeled indicative; a target met only at the point estimate is reported that way (VULN-04). |
| P9-10 | Retrieval effects | No entity or keyphrase boosting in Phase 9. | Boosting changes rankings and the calibrated scales; it belongs with Phase 10 measurement. |
| P9-11 | Lockfile hashes (VULN-08) | Hash the new Phase 9 packages now; convert the whole `requirements.lock.txt` to a hashed lock as a separate chore after Phase 9. | The current lock pins versions without hashes. Hashing everything at once touches every Phase 1 to 8 dependency and needs its own clean-install check. |
| P9-12 | Regex safety (VULN-06) | Every pattern uses unambiguous repetition: no nested quantifiers over overlapping classes. Gazetteer aliases are escaped literals in one compiled alternation, longest first. Each pattern has an adversarial test, such as 100,000 characters of `a.` or `--`: five times the input must cost under twelve times the time (quadratic would be about 25), within 3 s. Input is bounded by the chunk hard bound, and per-document enrichment time is in the report. | Python's `re` has no timeout, and a bounded-time engine would be another dependency. The BM25 `TECHNICAL` pattern, which P9-3 reuses, already alternates disjoint classes (`\w` and separators), so it runs in linear time. |

## Work sequence

Each step ends with offline tests passing. Steps 2 and 3 run in parallel; scoring against gold data waits until that data is frozen.

| Step | Work | Output and check |
|---|---|---|
| 0 | Entry decisions above; approve P9-1 to P9-12 or amend them | Recorded in [decisions](DECISIONS.md) as Phase 9 contracts |
| 1 | **Dependency gate** in a scratch environment: install spaCy, YAKE and, if needed, the spaCy model wheel against the current lock; `pip check`; confirm licenses of every new transitive package, install size, determinism over 3 runs and no network use at run time; run `pip-audit` (as a tool in the scratch environment, not a project dependency) over the full resulting environment; record the SHA-256 of every new wheel; reinstall offline from that local wheelhouse with `--require-hashes` | Pass: pins added to `pyproject.toml` and the lock, with the model as a hashed URL and the new packages' hashes recorded; no known vulnerability without a recorded disposition. Whether to hash the whole existing lock is decision P9-11. Fail: switch to the named alternative and record it. |
| 2 | **Gold data**: annotation guidelines and sheets (sheets in the ignored `data/`); you annotate 20 entity chunks and 5 key-term documents; review the drafted 50-sentence set; freeze with hashes and a review log | `datasets/nlp/{segmentation,entities,keyphrases}_gold.jsonl`, `datasets/nlp/review_log.md` |
| 3 | **Storage and command**: schema v3 migration with backup; `enrich [version_ids ...]` after `index`; skip unchanged work; delete and re-chunk handling; enrichment shown by a read-only command | Migration, idempotence and lifecycle tests; AC-07.2 |
| 4 | **Entities (FR-07)**: gazetteer and regex extractor; verified memberships feed `--entity` in both modes | AC-07.1, AC-07.3, withdrawal and deletion leave no stale matches (AC-12.4, AC-13.5) |
| 5 | **Keyphrases (FR-08)** with YAKE | AC-08.1, AC-08.2 |
| 6 | **Classification (FR-09)** with user precedence, `unclassified` threshold and the P9-7 filter | AC-09.2, AC-09.3 in tests; threshold proposal in the report |
| 7 | **Segmentation (FR-06 P1)**: spaCy policy with technical rules; measure against P0; adoption decision P9-2 | AC-06.4; if adopted, re-chunk, re-index, `eval` and threshold review |
| 8 | **Evaluation**: `eval --enrichment` writes a report with AC-06.4, AC-07.4, AC-08.3, AC-09.1 and AC-09.2, enrichment config IDs and run times; a real-model check classifies the out-of-topic fixtures in memory, without writing to the registry; `eval` fingerprint compared before and after `enrich` | `reports/evaluation/enrichment_*`; identical retrieval fingerprint |
| 9 | Phase 9 report, traceability, README and roadmap; full offline suite | `docs/PHASE_9_STATUS.md` |

Step 7 is last and isolated, so a spaCy gate failure does not hold up FR-07 to FR-09.

## Progress (2026-11-12)

| Step | State |
|---|---|
| 0 Decisions | ✅ Approved 2026-11-07 |
| 1 Dependency gate | ✅ Passed; spaCy 3.8.18 kept, YAKE replaced by `rake-nltk` 1.0.6 (license) |
| 2 Gold data | ✅ Frozen 2026-11-12: labeled by Fable 5.1, the owner-approved AI annotator (a recorded deviation), sentence draft reviewed without changes; 10 out-of-topic fixtures ([review log](../datasets/nlp/review_log.md)) |
| 3 Storage and command | ✅ Schema v3 with verified backup (migration hang fixed 2026-11-12), `enrich`, read-only `enrichment`; the real registry migrated |
| 4 Entities | 🟡 AC-07.1 to AC-07.3 met, on the real corpus too; AC-07.4 not met (precision 0.730, recall 0.491). Rules v2 and the revised gazetteer built; round 2 not yet measured |
| 5 Keyphrases | 🟡 AC-08.1 and AC-08.2 met; AC-08.3 not met (0 of 72 key terms in the top 10 with any RAKE metric). P9-5 amended: `technical-ngrams-v1` built as the default; round 2 not yet measured |
| 6 Classification | ✅ Threshold 0.649099 adopted and approved 2026-11-12; AC-09.1 met at the point estimate (19 of 20), AC-09.2 and AC-09.3 met; P9-6 secondary-category rule kept |
| 7 Segmentation | ✅ spaCy policy v2 ties the rules (boundary F1 0.989, AC-06.4 met at the point estimate); P9-2 keeps chunking on the rules |
| 8 Evaluation | ✅ `eval --enrichment` built and run; retrieval fingerprint identical before and after `enrich` |
| 9 Report | ✅ [Phase 9 report](PHASE_9_STATUS.md), with the gold-set results |

## Provenance

Every enrichment row and report records, so any result can be reproduced and two runs compared (VULN-10):

| Item | Where it comes from |
|---|---|
| Corpus identity | Manifest fingerprint and the per-document corpus fingerprint used by `eval` |
| Chunking | `chunking_config_id` and chunk snapshot hash per document |
| Enrichment | `enrichment_config_id`, hashing the gazetteer, the category descriptions, the regex pattern set, the extractor and classifier policy IDs and their thresholds |
| Inputs hashed separately | Gazetteer SHA-256, category-description SHA-256, each gold file's SHA-256 |
| Models | Embedding model name and digest; spaCy model version and wheel SHA-256 when used |
| Environment | Python and library versions, as `eval` reports already list them, plus the SHA-256 of `requirements.lock.txt` |
| Runs | Enrichment run ID, the classification threshold's calibration run ID, and the code version |

## Planned configuration

```toml
[enrichment]
gazetteer = "gazetteer.toml"
entity_verification_threshold = 0.5
keyphrases_per_document = 10
keyphrases_per_chunk = false
classification_method = "embedding"
max_categories = 3
# unclassified_threshold, calibration_run_id and similarity_config_id are added from an evaluation run, as in Phase 8.

# One table per configured category; each description is written and frozen before the first measurement.
[[enrichment.categories]]
name = "Distributed streaming"
description = "Event streaming platforms: topics, partitions, producers, consumers and brokers."
```

The four configured categories are the ones the corpus represents: Distributed streaming (4 documents), Workflow orchestration (4), Distributed computing (5) and Databases (7). Caching and the other FR-09 categories appear only in test fixtures.

## Your time

These are rough estimates for the human work that cannot be delegated:

| Task | Estimate |
|---|---|
| Approve or amend P9-1 to P9-12 | 30 minutes |
| Entity labels for 20 chunks of about 1,000 characters | 1 to 1.5 hours |
| Key terms for 5 documents, chosen for length under about 30 chunks across 4 technologies and 3 formats | 30 to 60 minutes |
| Review the drafted 50-sentence segmentation set | 15 to 30 minutes |

## Risks

- **Small gold sets.** 20 chunks and 5 documents give noisy figures; results are reported as indicative with their denominators.
- **Circular labels.** The person who writes the gazetteer should not label its test set. P9-9 puts the labels with you and freezes the gazetteer first.
- **Ambiguous names.** `spark`, `airflow` and `kafka` are also ordinary words or substrings of identifiers such as `kafka-topics.sh`. The guidelines decide how these count, and the gold set measures the result.
- **Dependency weight.** spaCy adds about a dozen packages, and the model wheel is hosted on GitHub rather than PyPI. The gate tests this before any code depends on it.
- **YAKE license.** LGPLv3 is normally fine for an unmodified dependency of a course project, but it is recorded and the RAKE alternative is ready.
- **DDIA.** It is enriched locally like any eligible document and is the only one without a user category, so it is the real multi-category case. It stays out of every gold set and report.
- **Re-chunking.** Adopting a new segmenter, or any later re-chunk, invalidates enrichment rows and calls for an `eval` rerun and a review of the Phase 8 threshold proposals. The scoring ID does not include the corpus, so the thresholds do not go stale on their own.

## Risk assessment (2026-11-07)

A specification-level review raised ten findings and recommended conditional approval. Each was checked against the code and settled in this plan as follows.

| ID | Finding | Checked against the code | Disposition |
|---|---|---|---|
| VULN-01 | Exact gazetteer matches verified without context | Valid. FR-07.2 itself sets confidence 1.0 for exact matches. | P9-3: ambiguous aliases need a context rule to count as exact, otherwise 0.4 and unverified; longest match; evidence stored. P9-9: ambiguous cases in the gold set. |
| VULN-02 | "No retrieval change" conflicts with new filters | Valid as worded. Unfiltered search reads no entity data (`retrieval/search.py`), and `eval` uses no filters. | [Invariants](#invariants): two separate invariants, with the fingerprint's scope stated. |
| VULN-03 | Classifier aggregation unspecified; similarity read as probability | Valid. | P9-6: aggregation, ranking, ties, threshold data and "similarity, not probability" specified. |
| VULN-04 | Small gold sets | Valid; the sizes are the requirement minimums. | P9-9: denominators, Wilson intervals, per-type, per-technology and per-format splits, confusion matrix, error lists, "indicative". |
| VULN-05 | Offsets assume preserved text | Partly mitigated: chunk text is an unaltered substring of normalized text. Raw-byte offsets were never offered. | P9-4: the reference text is the normalized text; a write-time check and normalization tests. |
| VULN-06 | Regex backtracking | Low for the existing pattern, which is linear. New patterns are not yet written. | P9-12: rules, adversarial tests, bounded input, timing. |
| VULN-07 | Migration and write recovery unspecified | Mostly handled by existing code: one `BEGIN IMMEDIATE` transaction per change and an OS registration lock (`REGISTRY_BUSY`). The backup was manual in Phase 5, and no test interrupts a write. | P9-8: automated, verified backup; per-document transactions; identity-checked reads; four failure tests. |
| VULN-08 | Supply chain | Valid. The lock has no hashes, and `pip-audit` is not installed. | Step 1: `pip-audit`, wheel hashes, offline `--require-hashes` reinstall. P9-11: full lock hashing later. |
| VULN-09 | Indirect prompt injection | Already mitigated in P0: delimited untrusted source blocks (FR-23.3), the live injection test (AC-23.3), secrets kept out of prompts (AC-23.4), and no tools to invoke. Phase 9 adds no LLM call. | Phase 9 puts no enrichment output into the prompt, and the invariant test checks it. If Phase 10 adds entities or keyphrases to the prompt, they go inside the delimited source blocks and the injection test is rerun. |
| VULN-10 | Traceability gaps | Valid in part. `eval` already records the dataset, corpus, configuration, model and libraries. | [Provenance](#provenance): the full list, including the gazetteer, description, gold and lockfile hashes. |

## Out of scope

Hybrid fusion, reranking, entity or keyphrase boosting, LLM-based extraction and the full benchmark belong to Phase 10. The P0 release decision belonged to the entry gate, which has passed.
