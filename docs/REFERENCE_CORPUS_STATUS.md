# Reference corpus assembly and verification

Reviewed 2026-10-24 on Windows/Python 3.13.3. Dataset: `techdocqa-reference-2026-10-24-v1`.

**21 selected local documents, 2,700,598 bytes (2.700598 MB; about 2.58 MiB), across five domains.** All are normalized, finalized and active, with distinct raw and normalized content hashes and no `duplicate_of` links. Source-byte size counts each selected document once; registry files, processed copies, preparation files and rejected candidates are not counted as additional corpus documents.

The frozen **public reference contains 20 documents, 1,513,828 bytes, across four technologies**. DDIA is a separately marked private supplement. The public selection independently meets the 15-30 document, 3-5 technology, <=50 MB, >=3 MD, >=3 HTML, >=3 text-PDF and >=1 TXT requirements. DDIA permissions/edition-conversion fidelity remain unverified, so the book is excluded from the DS-04 public reference.

The [manifest](../datasets/corpus_manifest.json) records all IDs, source keys, paths, source/normalized hashes, license evidence, review outcomes, source versions, PDF page mappings and the rejected candidate. [Reproduction and verification](../datasets/README.md) use the existing CLI and processing APIs. Catalog and SQLite registry remain authoritative; the manifest freezes the reviewed selection.

## Counts

For storage context, the whole private `data/` tree is 27,649,097 bytes in 125 files, including registry, preparation manual, rejected source and processing artifacts. Even that broader total is below 50 MB. Temporary tests/rendering tools under `.tmp` are excluded from corpus storage.

| Technology/domain | MD | HTML | PDF | TXT | Documents | Source bytes |
|---|---:|---:|---:|---:|---:|---:|
| Apache Airflow | 0 | 4 | 0 | 0 | 4 | 655,171 |
| Apache Kafka | 0 | 4 | 0 | 0 | 4 | 453,437 |
| Apache Spark | 3 | 2 | 0 | 0 | 5 | 131,168 |
| Designing Data-Intensive Applications | 1 | 0 | 0 | 0 | 1 | 1,186,770 |
| PostgreSQL | 0 | 3 | 3 | 1 | 7 | 274,052 |
| **Total** | **4** | **13** | **3** | **1** | **21** | **2,700,598** |

Excluding DDIA: **3 MD, 13 HTML, 3 PDF, 1 TXT; 20 documents; 4 technologies**.

## Each selected document

Every row has processing status **normalized**, `finalized=true`, `is_active=true`. Review status is accepted except DDIA, accepted only as a private supplement. URLs link to upstream provenance; the actual local paths and immutable hashes are in the manifest.

| Technology | Title/source | Format | Bytes | Review |
|---|---|---|---:|---|
| Apache Airflow | [Architecture Overview — Airflow 3.3.2 Documentation](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html) | html | 132,189 | Accepted |
| Apache Airflow | [Dag Runs — Airflow 3.3.2 Documentation](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html) | html | 136,824 | Accepted |
| Apache Airflow | [Dags — Airflow 3.3.2 Documentation](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html) | html | 229,316 | Accepted |
| Apache Airflow | [Tasks — Airflow 3.3.2 Documentation](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/tasks.html) | html | 156,842 | Accepted |
| Apache Kafka | [Design \| Apache Kafka](https://kafka.apache.org/43/design/design/) | html | 146,232 | Accepted |
| Apache Kafka | [Introduction \| Apache Kafka](https://kafka.apache.org/43/getting-started/introduction/) | html | 73,550 | Accepted |
| Apache Kafka | [Producer Configs \| Apache Kafka](https://kafka.apache.org/43/configuration/producer-configs/) | html | 146,845 | Accepted |
| Apache Kafka | [Quick Start \| Apache Kafka](https://kafka.apache.org/43/getting-started/quickstart/) | html | 86,810 | Accepted |
| Apache Spark | [Cluster Mode Overview](https://raw.githubusercontent.com/apache/spark/v4.0.1/docs/cluster-overview.md) | md | 7,026 | Accepted |
| Apache Spark | [Generic Load/Save Functions - Spark 4.0.1 Documentation](https://spark.apache.org/docs/4.0.1/sql-data-sources-load-save-functions.html) | html | 67,545 | Accepted |
| Apache Spark | [Hardware Provisioning](https://raw.githubusercontent.com/apache/spark/v4.0.1/docs/hardware-provisioning.md) | md | 4,541 | Accepted |
| Apache Spark | [Submitting Applications - Spark 4.0.1 Documentation](https://spark.apache.org/docs/4.0.1/submitting-applications.html) | html | 29,974 | Accepted |
| Apache Spark | [Tuning Spark](https://raw.githubusercontent.com/apache/spark/v4.0.1/docs/tuning.md) | md | 22,082 | Accepted |
| Designing Data-Intensive Applications | Designing Data-Intensive Applications (existing user-provided local conversion; no external source acquisition) | md | 1,186,770 | Private supplement; permissions unverified |
| PostgreSQL | [PostgreSQL 18 Tutorial: 1. Getting Started](https://www.postgresql.org/files/documentation/pdf/18/postgresql-18-A4.pdf) | pdf | 18,970 | Accepted |
| PostgreSQL | [PostgreSQL 18 Tutorial: 2. The SQL Language](https://www.postgresql.org/files/documentation/pdf/18/postgresql-18-A4.pdf) | pdf | 32,673 | Accepted |
| PostgreSQL | [PostgreSQL 18 Tutorial: 3. Advanced Features](https://www.postgresql.org/files/documentation/pdf/18/postgresql-18-A4.pdf) | pdf | 29,743 | Accepted |
| PostgreSQL | [PostgreSQL: Documentation: 18: 11.2. Index Types](https://www.postgresql.org/docs/18/indexes-types.html) | html | 26,200 | Accepted |
| PostgreSQL | [PostgreSQL: Documentation: 18: 13.2. Transaction Isolation](https://www.postgresql.org/docs/18/transaction-iso.html) | html | 47,642 | Accepted |
| PostgreSQL | [PostgreSQL: Documentation: 18: 14.1. Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html) | html | 70,029 | Accepted |
| PostgreSQL | [The PostgreSQL Transaction System](https://raw.githubusercontent.com/postgres/postgres/9412c35035a74b9e5623b4d7e67c5f77967f0d1a/src/backend/access/transam/README) | txt | 48,795 | Accepted |

## Acquisition, formats and PDF preparation

- Inspected requirements DS-01 through DS-05; the roadmap, LangChain ingestion plan, decisions, Phase 3A/3B checkpoints, default catalog and actual CLI/parser/loader/processing implementation.
- Phase 3A accepts finite approved **HTML/XHTML only**. It supplied the 13 selected HTML documents. PostgreSQL and Spark were enabled with explicit selected version-scoped URLs; Kafka/Airflow lists were narrowed to useful pages. Redis and Docker remain disabled. No crawling, site mirroring, JavaScript rendering or subresource acquisition occurred.
- Existing local registration and offline processing supplied three original Spark Markdown source files, the PostgreSQL transaction-system plain-text README, and the PDF chapter files. No parallel ingestion implementation or application architecture change was made.
- Four robots files were retrieved and reviewed; selected paths were allowed. Non-HTML source preparation used fixed public official HTTPS endpoints, public-address validation and pinned hostname TLS using existing project validation helpers, identity encoding, no automatic redirects, a 20 MiB response bound and connection/read deadlines. Actual sources and acquisition hashes are retained in ignored `data/corpus-acquisition` and projected into the manifest.
- Spark Markdown is pinned to `v4.0.1`; PostgreSQL TXT to commit `9412c35035a74b9e5623b4d7e67c5f77967f0d1a`. Airflow stable pages identify themselves as **3.3.2**, Kafka pages as **4.3** (quickstart examples use 4.3.1), Spark HTML as **4.0.1**, and the PostgreSQL PDF as **18.6**.

The PDF parent is the official [PostgreSQL 18 A4 manual](https://www.postgresql.org/files/documentation/pdf/18/postgresql-18-A4.pdf), 15,864,875 bytes, 3,156 pages. It was downloaded once as preparation material and not registered or counted in the corpus. Its SHA-256 is `9c6af8d2c8f0eda1b05e510bd8028f752162d2f5ce2db405bbf197336ce638d2`.

| PDF chapter | Original body physical pages | Original printed pages | Excerpt pages including legal notice |
|---|---|---|---:|
| Getting Started | 42-45 | 3-6 | 5 |
| The SQL Language | 46-55 | 7-16 | 11 |
| Advanced Features | 56-63 | 17-24 | 9 |

These are three distinct, nonoverlapping chapter documents derived from **one manual**, not three independently published PDF manuals. Each retains original physical page 2 containing the full legal notice. Existing pypdf 6.21.1 copies pages without reflow; cross-manual link annotations are omitted to avoid recursively cloning unrelated references. Every copied page was reopened and checked for exact extracted-text equality and unchanged page geometry against its parent. All 25 excerpt pages have >100 extracted characters, were rendered with PDFium, and were visually inspected in contact sheets; chapter starts, SQL examples, tables, margins and legal notices are intact. Excerpt page numbering starts at 1; original-page mappings are explicit in the manifest.

## Rejections and duplicate checks

The [Spark Data Sources overview](https://spark.apache.org/docs/4.0.1/sql-data-sources.html) was successfully processed but **rejected during review** because its extracted text was mostly a contents/navigation list. It was replaced by the substantive [Generic Load/Save Functions](https://spark.apache.org/docs/4.0.1/sql-data-sources-load-save-functions.html) page. Its 19,756 source bytes and document/version IDs are recorded under `rejected_documents` and excluded from corpus totals.

The registry therefore contains **22 normalized/active documents; only 21 are selected, and only 20 are public-reference entries**. There is no existing CLI review-rejection/withdrawal command, so the rejected record remains intact in registry history. Future evaluation must use the manifest selection rather than all active records.

There are **0 exact-byte or normalized-content duplicate documents** among the 21 selected entries. Repeating the initial Kafka acquisition reused four existing registrations; it did not create four extra documents. DDIA was skipped unchanged during processing. Shared PDF legal-notice text and topic overlap are disclosed; distinct whole-document hashes do not imply absence of repeated passages.

No selected document failed registration or processing. During preparation, outline title matching and cross-document PDF annotation recursion were corrected before writing successful excerpts; the temporary Windows output runner was changed to capture UTF-8. No incomplete result was counted.

## License and content-review limitations

- **PostgreSQL:** its [documentation legal notice](https://www.postgresql.org/docs/18/legalnotice.html) explicitly grants use, copying, modification and distribution subject to retention of its notices/disclaimers. Full legal notices are retained in all three PDF excerpts; upstream evidence remains local.
- **Apache projects:** the [Apache License page](https://www.apache.org/licenses/LICENSE-2.0) and official project provenance were reviewed. Spark source files explicitly include the Apache-2.0 notice; the pinned LICENSE and NOTICE were acquired. Registry metadata declares Apache-2.0 for Kafka/Airflow/Spark and PostgreSQL for PostgreSQL. These declarations do not remove notice/trademark/third-party obligations. No downloaded bodies were staged or published.
- **DDIA:** original local Markdown exists and its prior normalized snapshot was verified without external transmission. Its registry license remains null; no redistribution right, completeness, accurate book conversion, or publicly available/open-license qualification is asserted. It is excluded from the frozen public reference.
- The existing HTML cleaner leaves some PostgreSQL release/version/feedback boilerplate and Spark SQL sidebar navigation. Body headings, useful technical tokens and examples were verified; the navigation-only Spark page was rejected. No site-specific parser architecture was added.
- Original Spark Markdown retains Jekyll front matter, raw HTML, relative image links and occasional template tokens. External images/includes were not fetched. These are source documents rather than a rendered website.
- Codex reviewed source provenance, samples/headings, required topic tokens, format correctness, page content and artifact integrity. This is not a line-by-line factual review of every document or an independent second-human review. DDIA review was limited to local structure/integrity.
- Mutable upstream pages can drift. Exact frozen-byte reproduction requires retained private snapshots or reacquisition matching the recorded hashes. Unexpected upstream changes must produce a new reviewed dataset version.

## Exact verification results

| Check | Actual result |
|---|---|
| `techdocqa config-check` | Exit 0, `configuration_valid`; models remain unselected and no provider connection is claimed. |
| Initial HTML batches | Kafka 4, Airflow 4, PostgreSQL 3, Spark 2 successful registrations; replacement Spark page also succeeded. Kafka repeat reused 4 entries. |
| Local registration | Seven selected reference files registered successfully: 3 MD, 3 PDF, 1 TXT. Existing DDIA registration preserved. |
| First corpus `process` | Run `run_16f2018160cc44fd8ad71a91b8c43630`: 20 processed, 1 unchanged skipped, 0 failed, 34.03 seconds. |
| Processing after Spark replacement | Run `run_f13bcf7a15a446a89548494664a53c98`: 1 processed, 21 skipped, 0 failed, 6.20 seconds; includes the retained rejected registry record. |
| Existing `list`, `status --status normalized`, `history` | Exit 0; all selected versions normalized/finalized/active; DDIA history retained. |
| `python datasets/verify_corpus.py` | Exit 0: 21 verified; 20 public reference; 2,700,598 bytes; 0 duplicate documents. Source hashes, normalized Documents and processing artifact integrity verified through existing APIs. |
| PDF preparation self-checks | 25/25 pages: original text equal, geometry equal, nonempty text; 25/25 rendered and visually reviewed. |
| PDF reproduction recipe | All 3 excerpts regenerated in memory with SHA-256 matching the frozen source bytes. |
| Documentation/source preservation | 47 local documentation links resolve; requirements SHA-256 remains `d458ddb2175d507004806738d3f87de41405d40d39676b52995e07db3d479949`. |
| First offline suite after expanding catalog | 191 passed, 23 failed, 2 skipped, 1 warning, 101.26 seconds. Failures exposed mocks coupled to one page/source and disabled PostgreSQL. |
| Online tests after fixture correction | 79 passed, 2 skipped, 1 warning, 14.22 seconds. |
| Final complete offline suite | **214 passed, 2 skipped, 0 failed**, 1 existing warning, **69.36 seconds**. |
| `python -m pip check` | Exit 0, `No broken requirements found.` |
| Git data protection | `git check-ignore` confirms corpus, registry, acquisition evidence and scratch are ignored; `git ls-files data` is empty. |
| `git diff --check` | Exit 0; no whitespace errors in the final tracked diff. New report/verifier files were checked separately for trailing whitespace. |

The two skips are the existing explicitly opt-in live Kafka/Airflow tests; actual corpus fetching/processing was executed separately. The existing warning is the archived/sunset `langchain-community` loader notice. Test fixtures now explicitly exercise one page per source with unreviewed/disabled states; the CLI test derives its mock response count from the real catalog. Application code, dependency declarations and lock are unchanged.

PDF visual review used pypdfium2 5.14.0 and Pillow 13.0.0 installed only under ignored `.tmp/corpus-assembly/pdf-render`; no project environment/dependency declaration change was made. There was no usable preinstalled PDF renderer or connected browser. Temporary renderers and acquisition intermediates are not selected corpus bytes.

Final reproducible checks:

```powershell
.\.venv\Scripts\techdocqa.exe config-check
.\.venv\Scripts\techdocqa.exe list --json
.\.venv\Scripts\techdocqa.exe status --status normalized --json
.\.venv\Scripts\python.exe datasets/verify_corpus.py
.\.venv\Scripts\python.exe -m pytest --basetemp=.tmp/corpus-assembly/pytest-final
.\.venv\Scripts\python.exe -m pip check
git -c safe.directory=C:/Users/Ubaid/Desktop/TechDocQA diff --check
```

## Remaining gates

No numeric document/format/technology/size requirement remains unmet for the 20-document public reference. Treating DDIA as a DS-04 public/openly licensed evaluation source remains unsupported. Three-PDF compliance uses disclosed chapter excerpts from one manual; any additional course rule requiring independently published manuals would require a different selection.

The approximate <=3,000-chunk target is unmeasured because chunking is not implemented. Hardware/budget/model selection, independent human review and benchmark preparation remain later gates. No chunking, embeddings, vector/BM25 indexes, retrieval, answer generation, model call, DDIA upload, public commit or push was performed.

Reference fingerprint: `a09e71fae4751538ce0b65b2a2341792a2bb4f0358805c1c8505f03f69c0d303`.
