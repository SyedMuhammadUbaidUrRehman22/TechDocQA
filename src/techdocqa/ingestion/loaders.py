"""Local framework loaders; called only inside the bounded processing worker."""

from importlib.metadata import version
from pathlib import Path

from langchain_core.documents import Document
from langchain_community.document_loaders.pdf import PyPDFLoader
from langchain_community.document_loaders.text import TextLoader

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.html import extract_html
from techdocqa.normalization import code_spans, headings
from techdocqa.privacy import safe_text


def load_documents(path: Path, doc_type: str, directory: Path, minimum: int) -> list[Document]:
    if doc_type == "html":
        result = extract_html(path.read_bytes(), directory, minimum)
        documents = [Document(page_content=(directory / "extracted.txt").read_bytes().decode("utf-8"),
                              metadata={key: result[key] for key in (
                                  "original_title", "encoding", "code_spans", "headings", "extraction_policy")})]
    elif doc_type == "pdf":
        loaded = PyPDFLoader(str(path), mode="page", extract_images=False).load()
        documents = [Document(page_content=doc.page_content, metadata={
            "page_index": doc.metadata["page"], "page": doc.metadata["page"] + 1,
            "total_pages": doc.metadata["total_pages"],
            "original_title": safe_text(doc.metadata.get("title", ""))[:1000] or None,
        }) for doc in loaded]
    elif doc_type in {"md", "txt"}:
        raw = path.read_bytes()
        try:
            text, encoding = raw.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            if doc_type != "txt":
                raise TechDocQAError("DECODE_FAILED", "Markdown must be valid UTF-8.", stage="extraction") from None
            text, encoding = raw.decode("latin-1"), "latin-1"
        if any(ord(char) < 32 and char not in "\t\r\n\f" or 0x7f <= ord(char) < 0xa0 for char in text):
            raise TechDocQAError("DECODE_FAILED", "Text contains unsupported control characters.", stage="extraction")
        document = TextLoader(str(path), encoding=encoding, autodetect_encoding=False).load()[0]
        # TextLoader uses universal newlines; recover decoded source newlines for exact code preservation.
        document.page_content = text
        spans = code_spans(text)
        sections = headings(text, spans) if doc_type == "md" else []
        title = next((section["text"] for section in sections if section["level"] == 1), None)
        document.metadata = {"encoding": encoding, "original_title": safe_text(title)[:1000] if title else None,
                             "headings": sections, "code_spans": spans}
        documents = [document]
    else:
        raise TechDocQAError("UNSUPPORTED_FORMAT", "Unsupported registered format.", stage="extraction")
    if sum(not char.isspace() for doc in documents for char in doc.page_content) < minimum:
        raise TechDocQAError("NO_TEXT_EXTRACTED", "Document contains too little usable text.", stage="extraction")
    dependencies = {name: version(name) for name in ("langchain-community", "langchain-core", "pypdf")}
    for document in documents:
        document.metadata.update(doc_type=doc_type, extraction_dependencies=dependencies)
    return documents
