# Dataset preparation

The manifest is explicitly a draft, not a selected or frozen corpus. No files, licenses, hashes, benchmark labels or review evidence have been fabricated. Corpus selection remains an open Phase 1 gate.

Before freezing it, select 15–30 public/openly licensed documents across 3–5 technologies, <=50 MB, including at least 3 Markdown, 3 HTML, 3 text PDFs and 1 TXT. Each document record must include source_key, relative local path, technology, format, source URL, license/terms, raw_hash (SHA-256 bytes) and content_hash (SHA-256 normalized text, computed after normalization exists). The approximate chunk target is <=3000. Keep the downloaded files under ignored data/corpus unless redistribution is explicitly permitted.

DS-05 synthetic fixtures are created with ingestion/parser tests in Phase 2–3; they must not enter the corpus. Smoke questions are authored only after corpus selection: 20 answerable + 10 unanswerable, stable source/section/text anchors, reviewed by a second person with disagreements recorded. Full benchmark retains smoke and has <=50 questions. Benchmark files and results are not created as empty placeholders.
