# LangChain loading and corpus preparation

Phase 4 update 2026-10-24: the installed/pinned `langchain-text-splitters==1.1.3` RecursiveCharacterTextSplitter is now used by `chunk`; no custom retrieval engine or new package installation was needed. It is declared directly in `pyproject.toml`. Local loading/normalization remains unchanged. See [chunking policy, counts, tokenizer fallback and acceptance limits](PHASE_4_STATUS.md); older statements about future splitting are historical.

Update 2026-10-24: the [reference corpus](REFERENCE_CORPUS_STATUS.md) is now selected, processed and frozen in `datasets/corpus_manifest.json`: 20 public reference documents plus one excluded private DDIA supplement. The zero-file/draft statements below describe the earlier preparation checkpoint. Local registration/processing supplies the Markdown, TXT and extracted PDF chapter files; Phase 3A supplies the selected HTML pages.

Reviewed 2026-10-22 against the dependency lock, requirements C-01/DS-01–DS-05/FR-01–FR-05/FR-10 and Phase 3B. The loading/normalization portion is now implemented; splitting remains Phase 4 and the corpus is unfrozen. See [Phase 3B status](PHASE_3B_STATUS.md) and [normalization/version contracts](DECISIONS.md#phase-3b-normalization-and-finalization-2026-10-22).

## Current dependency boundary

Phase 3A execution update: online HTML now uses `langchain-community==0.4.2` BSHTMLLoader with BeautifulSoup 4.15.0 and the standard-library `html.parser`, after TechDocQA's validated urllib3 fetch. No lxml, browser, OCR or paid scraping integration is required. The loader package's [upstream archive notice](https://github.com/langchain-ai/langchain-community/issues/674) is an explicit maintenance limitation. Its required transitive dependencies include `langchain-classic` and `langchain-text-splitters`; installation does not mean splitting or the remaining local loaders are implemented. The Phase 2 dependency inventory and future-format plan below remain historical context.

See [Phase 3A checkpoint](PHASE_3A_STATUS.md) for historical evidence. The adapter preserves whole pages, heading hierarchy and exact decoded block/inline code via placeholders with recorded text offsets; framework loader metadata cannot overwrite registry-owned provenance. Raw HTML and UTF-8 extracted text have distinct hashes and content-addressed relative paths. HTTP charset is decoded strictly when declared; otherwise BeautifulSoup's detected encoding is recorded. Missing/invalid titles warn and use the catalog's source title as display fallback, leaving `original_title=null`. Phase 3B consumes these saved artifacts offline, adds FR-04 normalized hashes and FR-05 finalization; Phase 4 chunks remain absent.

The lock contains LangChain 1.4.4, langchain-core 1.6.9 and langchain-ollama 1.1.0. Phase 2 added pypdf 6.21.1 for page-count preflight; Phase 3A added the community loader/BeautifulSoup stack. Phase 3B reuses these exact installed packages, including TextLoader and page-mode PyPDFLoader, with no dependency/lock changes. Installed text splitters remain unused until Phase 4.

Registration supports exactly the requirement's `.md`, `.markdown`, `.html`, `.htm`, `.pdf` and `.txt` inputs. These formats now use the following LangChain paths in the bounded offline processing worker; Phase 3B synthetic tests verify them against the existing lock.

| Format | Planned framework loading | Preservation / later acceptance gate |
|---|---|---|
| Markdown | `langchain_community.document_loaders.TextLoader` with explicit UTF-8; preserve the raw Markdown returned by framework loading | Preserve fenced/inline code and headings before normalization. Carry hierarchy into `section_path`; use framework Markdown heading-aware splitting in Phase 4 with fence-preservation regression fixtures. No Unstructured/OCR stack is needed just to read Markdown. |
| HTML / HTM | `langchain_community.document_loaders.BSHTMLLoader` backed by BeautifulSoup | Default plain-text conversion is insufficient for all FR-03 structure/code rules. A small adapter around the framework loader must remove required boilerplate while preserving headings/lists/pre/code and section metadata. Verify marker removal and intact technical text before selecting exact options. |
| Text-based PDF | `langchain_community.document_loaders.PyPDFLoader` backed by pypdf, configured for page-level loading and no OCR/image extraction | Preserve each loader page and original page index; expose 1-based citation `page` consistently. Retain total page count. Image-only documents may register in Phase 2, but must fail `NO_TEXT_EXTRACTED` in Phase 3. |
| TXT | Framework `TextLoader`, explicit UTF-8 then documented Latin-1 fallback | Record the chosen encoding; detect/reject garbled/binary content rather than silently accepting it. No text is decoded by Phase 2 registration. |

Verified upstream implementation references: [TextLoader](https://github.com/langchain-ai/langchain-community/blob/main/libs/community/langchain_community/document_loaders/text.py), [BSHTMLLoader](https://github.com/langchain-ai/langchain-community/blob/main/libs/community/langchain_community/document_loaders/html_bs.py), [PyPDFLoader](https://github.com/langchain-ai/langchain-community/blob/main/libs/community/langchain_community/document_loaders/pdf.py). The maintained source locates these in `langchain_community.document_loaders`; it also identifies the BeautifulSoup/pypdf dependencies. These links document a later integration choice, not a newly installed loader.

Phase 4 must use `langchain_text_splitters` framework splitters, including recursive/Markdown-aware splitting where acceptance fixtures support it. The [framework Markdown splitter implementation](https://github.com/langchain-ai/langchain/blob/master/libs/text-splitters/langchain_text_splitters/markdown.py) exposes heading-aware behavior, but default whitespace/fence handling must be checked against our byte-preservation requirements. Do not replace framework loading or splitting with an unrelated custom RAG pipeline.

## Metadata propagation contract

Registry records expose the following document-level values so they can be copied into each LangChain `Document.metadata` after loading. An offline test constructs a framework `Document` with the persisted record metadata, without loading any content.

| Registry field | Later framework metadata / meaning |
|---|---|
| `document_id`, `version_id`, `source_key` | Stable source identity and resolved finalized version identity. A Phase 2 version ID is provisional until normalization. |
| `source_url`, `filename` | Sanitized public source URL and source label. Private registry paths are not exposed in CLI records. |
| `technology`, `category`, `title`, `version_label`, `language` | Explicit source metadata; title later follows user > format title > filename. Version label is distinct from the registry version ID. |
| `license` | License identifier or terms note; registration preserves this declaration but does not verify licensing. |
| `raw_hash` | SHA-256 of the exact original file bytes, computed independently before loading. Never replace this with a hash of extracted text. |
| `content_hash` | SHA-256 of UTF-8 normalized text; null until finalized. A normalized duplicate byte candidate keeps null here and links to its resolved finalized version through `processing`. Never fabricated from byte hashes. |
| `doc_type`, `size_bytes`, `page_count` | Registered format, actual byte size and PDF preflight page count. |
| later `page`, `section_path`, offsets | Derived only when a loader/splitter exposes verified page/heading/source structure. Never assign invented page or section data during registration. |

Phase 3 must use a captured snapshot or verify the current bytes still match the registered `raw_hash` before loading. Protect registry-owned IDs/hash/license/source metadata from accidental replacement by a loader's own metadata keys. Preserve both upstream page indices and the agreed display numbering. Later vector projections can omit null values as required by the store; the registry retains the full source record.

## Corpus work still open

`datasets/corpus_manifest.json` remains draft with zero files. Select 15–30 permitted files across 3–5 technologies, at most 50 MB, with >=3 Markdown, >=3 HTML, >=3 text PDFs and >=1 TXT. Keep source URL, license/terms and byte hash for each; normalized hash and document/version IDs are filled only by verified later processing. Review licenses and PDF text availability before freezing the corpus. Registration of a PDF does not prove it is text-based.

Synthetic tests generate duplicate, modified, renamed, image-only PDF, unsupported and Latin-1 cases separately from the corpus. Phase 3B adds executed local loading, section/page preservation, normalized deduplication, worker deadlines and content hashes. The tests establish synthetic behavior, not full corpus parser quality. No corpus acquisition, splitting, embeddings, retrieval or model selection is performed.
