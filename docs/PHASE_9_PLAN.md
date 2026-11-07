# Phase 9 plan: P1 NLP enrichment

Status: **proposed 2026-11-04, not approved.** Nothing in this plan is implemented. It covers roadmap Phase 9: FR-06 full, FR-07, FR-08, FR-09 and their FR-12/FR-13 filter extensions. Sources: [Revision 3 requirements](../TechDocQA_Requirements_v2.md), [roadmap](IMPLEMENTATION_ROADMAP.md#phase-9--p1-nlp-enrichment), [decisions](DECISIONS.md) D-08, Q-11, Q-14 and Q-16, and the [Phase 8 report](PHASE_8_STATUS.md).

## Entry gate

The roadmap puts Phase 9 after the P0 release gate, and that gate is blocked:

| Blocker | What clears it |
|---|---|
| AC-16.6 | You rate the 10 answers in `data/evaluation/answers_d724f334f9f0409884db95613c61663e_review.md`; at least 8 must be supported. If fewer are, answer quality needs work before P1. |
| AC-12.1 | 124 of 152 sentence queries on the real corpus. It needs a fix or an approved amendment. P1 hybrid search does not make vector search itself pass, so it is not a fix for this criterion as written. |
| Q-07, Q-12, Q-13 | Approve or amend; this changes recorded policy IDs, not code. |

**Recommendation:** rate AC-16.6 first. Then start Phase 9 alongside the AC-12.1 decision, with P0 still marked unreleased. Phase 9 must not change retrieval or answers. Each run proves that: `eval` gives the same `results_fingerprint` before and after enrichment, so the Phase 8 calibration stays valid.

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
| AC-09.2 | Out-of-topic document gets `unclassified` | Test with the fake embedder; real-model check on fixture texts | Cooking article plus 2 to 4 other out-of-topic fixtures |
| AC-09.3 | `category=Caching` returns no other category | Test fixture; real check with `category=Databases` | none |

## Decisions to approve before coding

| ID | Decision | Recommendation | Why, and the alternative |
|---|---|---|---|
| P9-1 | Libraries (D-08) | **spaCy 3.8.18** for FR-06 P1 (MIT; Windows wheel for Python 3.13 on PyPI). **YAKE 0.7.3** for FR-08 (pure Python, **LGPLv3**). No KeyBERT, torch or LLM extraction. Both must pass the dependency gate in step 1. | spaCy is the requirement's own example. YAKE is light and deterministic, and its lower-is-better score maps to a descending score. Alternative: RAKE (`rake-nltk`, MIT), which needs NLTK and a stop-word download. |
| P9-2 | Segmenter adoption | Measure P0 rules, the spaCy `sentencizer` with technical rules, and, if needed, the `senter` from `en_core_web_sm` 3.8.0 on the same gold set. Make spaCy a selectable segmentation policy. Use it for chunking only if it beats the rules and you accept the rerun. | Chunking under a new policy means re-chunking 21 documents, re-indexing (548 s last time), rerunning `eval` and reviewing the Phase 8 threshold proposals. Keeping chunking on P0 rules leaves every Phase 5 to 8 result intact. |
| P9-3 | Entity extractor | A gazetteer in `config/gazetteer.toml` (canonical name, aliases, type, optional technology-to-category link) plus regex patterns for `IDENTIFIER` and `PROTOCOL`. Confidence 1.0 for exact gazetteer matches, lower fixed values per regex pattern; below 0.5 means `verified=false` (Appendix A). No model-based extractor. | FR-07 requires rules. A regex matcher keeps technical tokens whole, where spaCy's tokenizer would split `linger.ms`. Ambiguous common words (`spark`, `airflow`) need case or context rules, set in the annotation guidelines. |
| P9-4 | Offsets (Q-11) | Half-open character offsets into the chunk text, plus document offsets derived from the chunk's source start. | Chunk offsets are what search returns; document offsets survive display. |
| P9-5 | Keyphrases | Top 10 per document, stored with rank, a descending `score` and the raw YAKE value. Per-chunk keyphrases are configurable and off by default. Whether code blocks count is decided by measurement on the gold set. Keyphrases do **not** enter BM25 text. | Adding them to BM25 would change its score scale, make the BM25 thresholds stale and double-count chunk words. Phase 10 can measure that with hybrid search. |
| P9-6 | Classifier | **Embedding similarity** as the default: the configured category descriptions are embedded once and compared with the document's stored chunk vectors. Up to 3 `(category, confidence)` pairs, with an `unclassified` threshold set like the Phase 8 thresholds and recorded with its run ID. A rule baseline, technology entities mapped to categories, is reported beside it. The classifier never reads the user-supplied technology or category. | It generalizes beyond named technologies and uses the framework embedder with no new document calls. Rules alone would score near 100% here, because each document names its technology, which says little. Alternative: rules as default, or a zero-shot `qwen3:1.7b` prompt, which is slower and less deterministic. The category descriptions are written and frozen before the first measurement. |
| P9-7 | Category filter (Q-16) | A document matches `category=X` when X is its user category; without one, when X is among its inferred categories at or above the threshold. `category=unclassified` is a valid filter. The Chroma `category` field keeps the registration value, and the registry decides filters, as it does today. | This keeps a single registry decision for both retrievers and AC-02.5 unchanged. The alternative, matching only the top inferred category, loses the multi-category behavior FR-09.2 asks for. |
| P9-8 | Storage | Registry schema version 3, additive and applied in place like version 2, after a backup copy. New tables: `entities` (all, with `verified`), `keyphrases`, `document_categories`; `verified_entities` is filled from verified entities in the same transaction. Rows carry the version, the chunking configuration and an `enrichment_config_id`. A new run stage `enrichment`; no new processing status (Q-02). | Per-document and per-chunk queries need SQL. Stale rows after re-chunking are replaced atomically by the next `enrich`, and `delete` removes them. |
| P9-9 | Gold data and metrics | You annotate the entity and key-term sets **before** seeing extractor output; Claude Code prepares sheets and guidelines and drafts the segmentation set for your review. Chunks are sampled by a fixed rule, 5 per technology from the public reference, never DDIA. The gazetteer is frozen and hashed before the entity set is scored; a later change needs a fresh sample or is reported as tuned. Committed gold files hold source keys, short anchors and labels, not whole chunks. | This avoids Phase 8's calibration-and-assessment overlap. Metric rules: boundary F1 on exact positions; entity precision and recall on (chunk, normalized text, type) mentions, micro-averaged; key-term hits on normalized exact match, with a lenient match reported only as a diagnostic; classification on top-1 against manifest labels. |
| P9-10 | Retrieval effects | No entity or keyphrase boosting in Phase 9. | Boosting changes rankings and the calibrated scales; it belongs with Phase 10 measurement. |

## Work sequence

Each step ends with offline tests passing. Steps 2 and 3 run in parallel; scoring against gold data waits until that data is frozen.

| Step | Work | Output and check |
|---|---|---|
| 0 | Entry decisions above; approve P9-1 to P9-10 or amend them | Recorded in [decisions](DECISIONS.md) as Phase 9 contracts |
| 1 | **Dependency gate** in a scratch environment: install spaCy, YAKE and, if needed, the spaCy model wheel against the current lock; `pip check`; confirm licenses, install size, determinism over 3 runs and no network use at run time | Pass: pins added to `pyproject.toml` and the lock, with the model as a hashed URL. Fail: switch to the named alternative and record it. |
| 2 | **Gold data**: annotation guidelines and sheets (sheets in the ignored `data/`); you annotate 20 entity chunks and 5 key-term documents; review the drafted 50-sentence set; freeze with hashes and a review log | `datasets/nlp/{segmentation,entities,keyphrases}_gold.jsonl`, `datasets/nlp/review_log.md` |
| 3 | **Storage and command**: schema v3 migration with backup; `enrich [version_ids ...]` after `index`; skip unchanged work; delete and re-chunk handling; enrichment shown by a read-only command | Migration, idempotence and lifecycle tests; AC-07.2 |
| 4 | **Entities (FR-07)**: gazetteer and regex extractor; verified memberships feed `--entity` in both modes | AC-07.1, AC-07.3, withdrawal and deletion leave no stale matches (AC-12.4, AC-13.5) |
| 5 | **Keyphrases (FR-08)** with YAKE | AC-08.1, AC-08.2 |
| 6 | **Classification (FR-09)** with user precedence, `unclassified` threshold and the P9-7 filter | AC-09.2, AC-09.3 in tests; threshold proposal in the report |
| 7 | **Segmentation (FR-06 P1)**: spaCy policy with technical rules; measure against P0; adoption decision P9-2 | AC-06.4; if adopted, re-chunk, re-index, `eval` and threshold review |
| 8 | **Evaluation**: `eval --enrichment` writes a report with AC-06.4, AC-07.4, AC-08.3, AC-09.1 and AC-09.2, enrichment config IDs and run times; a real-model check classifies the out-of-topic fixtures in memory, without writing to the registry; `eval` fingerprint compared before and after `enrich` | `reports/evaluation/enrichment_*`; identical retrieval fingerprint |
| 9 | Phase 9 report, traceability, README and roadmap; full offline suite | `docs/PHASE_9_STATUS.md` |

Step 7 is last and isolated, so a spaCy gate failure does not hold up FR-07 to FR-09.

## Planned configuration

```toml
[enrichment]
gazetteer = "gazetteer.toml"
entity_verification_threshold = 0.5
keyphrases_per_document = 10
keyphrases_per_chunk = false
classification_method = "embedding"
max_categories = 3
# unclassified_threshold and its calibration run ID are added from an evaluation run, as in Phase 8.

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
| Approve or amend P9-1 to P9-10 | 30 minutes |
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

## Out of scope

Hybrid fusion, reranking, entity or keyphrase boosting, LLM-based extraction and the full benchmark belong to Phase 10. AC-12.1 and the P0 release decision stay with the entry gate.
