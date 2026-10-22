from pathlib import Path

import pytest

from techdocqa.ingestion.pipeline import register_paths
from techdocqa.ingestion.processing import finalized_documents, process_versions
from techdocqa.schemas import RegistrationMetadata

TEXT = "Kafka consumer.group configures max.poll.interval.ms. Airflow uses dag_id and airflow tasks test. " * 3


@pytest.mark.parametrize("suffix", ["txt", "md", "html", "pdf"])
def test_all_local_formats_use_framework_loaders_with_citation_metadata(suffix, corpus, settings, registry, pdf_factory):
    source = corpus / ("technical." + suffix)
    if suffix == "pdf":
        source.write_bytes(pdf_factory(pages=2))
    elif suffix == "html":
        source.write_text("<html><head><title>Format title</title></head><body><nav>NAV_MARKER</nav><main>"
                          "<h1>Setup</h1><p>" + TEXT + "</p><pre>if dag_id:\n    print('consumer.group')\n</pre>"
                          "</main><footer>FOOTER_MARKER</footer></body></html>", encoding="utf-8", newline="\n")
    else:
        source.write_text(("# Format title\n## Setup\n" if suffix == "md" else "") + TEXT, encoding="utf-8")
    candidate = register_paths([source], settings, registry, metadata=RegistrationMetadata(technology="Kafka")).outcomes[0].result
    batch = process_versions([candidate.version_id], settings, registry)
    assert batch.run.processed == 1, batch.model_dump_json()
    documents = finalized_documents(candidate.version_id, settings, registry)
    if suffix == "pdf":
        assert len(documents) == 2
        assert [doc.metadata["page"] for doc in documents] == [1, 2]
        assert [doc.metadata["page_index"] for doc in documents] == [0, 1]
        assert all("Kafka stores events. Redis stores keys. PostgreSQL stores rows." in doc.page_content for doc in documents)
    else:
        assert "max.poll.interval.ms" in documents[0].page_content
    if suffix == "html":
        assert "NAV_MARKER" not in documents[0].page_content and "FOOTER_MARKER" not in documents[0].page_content
        assert "if dag_id:\n    print('consumer.group')\n" in documents[0].page_content
    if suffix in {"md", "html"}:
        assert registry.get_document(candidate.document_id).title == "Format title"
    assert documents[0].metadata["technology"] == "Kafka"
    assert str(source) not in documents[0].metadata.__repr__()
    info = registry.get_document(candidate.document_id).processing
    assert (Path(settings.data_directory) / info.extracted_path).is_file()


def test_image_only_pdf_has_registered_failure_state(corpus, settings, registry, pdf_factory):
    source = corpus / "image.pdf"
    source.write_bytes(pdf_factory(image_only=True))
    candidate = register_paths([source], settings, registry).outcomes[0].result
    result = process_versions([candidate.version_id], settings, registry)
    assert result.outcomes[0].error.code == "NO_TEXT_EXTRACTED"
    assert registry.get_version(candidate.version_id).status == "extraction_failed"


def test_latin1_fallback_records_encoding_and_invalid_markdown_fails(corpus, settings, registry):
    text = corpus / "latin.txt"
    text.write_bytes(("Caf\u00e9 " + TEXT).encode("latin-1"))
    md = corpus / "latin.md"
    md.write_bytes(text.read_bytes())
    candidates = register_paths([text, md], settings, registry)
    result = process_versions([item.result.version_id for item in candidates.outcomes], settings, registry)
    assert result.run.processed == result.run.failed == 1
    assert result.outcomes[1].error.code == "DECODE_FAILED"
    record = registry.get_version(result.outcomes[0].result.version_id)
    assert record.processing.encoding == "latin-1"
    assert "Caf\u00e9" in finalized_documents(record.version_id, settings, registry)[0].page_content


def test_user_title_precedence_and_pdf_metadata_title(corpus, settings, registry, pdf_factory):
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf_factory(pages=2))))
    writer.add_metadata({"/Title": "PDF metadata title"})
    source = corpus / "title.pdf"
    writer.write(source)
    candidate = register_paths([source], settings, registry).outcomes[0].result
    assert process_versions([candidate.version_id], settings, registry).run.processed == 1
    assert registry.get_document(candidate.document_id).title == "PDF metadata title"
    md = corpus / "title.md"
    md.write_text("# Format title\n" + TEXT, encoding="utf-8")
    candidate = register_paths([md], settings, registry, metadata=RegistrationMetadata(title="User title")).outcomes[0].result
    process_versions([candidate.version_id], settings, registry)
    assert registry.get_document(candidate.document_id).title == "User title"
