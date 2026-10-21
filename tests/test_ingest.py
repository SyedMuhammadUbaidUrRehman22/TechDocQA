import hashlib

import pytest

from techdocqa.ingestion.pipeline import register_paths
from techdocqa.schemas import RegistrationMetadata


def test_four_supported_formats_register_with_required_metadata(corpus, settings, registry, pdf_factory):
    files = {
        "one.md": b"# Kafka Basics\nRegistration preserves original bytes.",
        "two.txt": b"Redis registration text.",
        "three.html": b"<html><title>PostgreSQL</title><p>SQL</p></html>",
        "four.pdf": pdf_factory(),
    }
    for name, data in files.items():
        (corpus / name).write_bytes(data)
    result = register_paths([corpus], settings, registry)
    assert result.run.processed == 4
    assert result.run.status == "completed"
    assert len({outcome.result.document_id for outcome in result.outcomes}) == 4
    for outcome in result.outcomes:
        record = registry.get_document(outcome.result.document_id)
        assert record.raw_hash == hashlib.sha256(files[record.filename]).hexdigest()
        assert record.status == "registered"
        assert record.content_hash is None and not record.finalized and not record.is_active
        assert record.title == record.filename  # Format-derived titles require Phase 3 loaders.
        assert record.technology is None and record.language == "en"
        assert record.ingested_at.endswith("+00:00")
        assert record.page_count == (1 if record.doc_type == "pdf" else None)


@pytest.mark.parametrize(("name", "data", "code"), [
    ("bad.docx", b"unsupported", "UNSUPPORTED_FORMAT"),
    ("bad.pdf", b"plain text", "FORMAT_MISMATCH"),
    ("empty.txt", b"", "EMPTY_FILE"),
    ("archive.md", b"PK\x03\x04payload", "ARCHIVE_NOT_ALLOWED"),
    ("binary.md", b"\x89PNG\r\n\x00", "FORMAT_MISMATCH"),
    ("missing.txt", None, "SOURCE_NOT_ACCESSIBLE"),
])
def test_invalid_file_outcomes_are_persisted(corpus, settings, registry, name, data, code):
    source = corpus / name
    if data is not None:
        source.write_bytes(data)
    result = register_paths([source], settings, registry)
    assert result.run.failed == 1 and result.run.status == "failed"
    error = registry.get_run(result.run.run_id).outcomes[0].error
    assert error.code == code and error.document_id is None
    if code == "UNSUPPORTED_FORMAT":
        assert "pdf, html, htm, md, markdown, txt" in error.message
    assert registry.list_documents() == []


def test_mixed_batch_preserves_every_success_and_failure(corpus, settings, registry):
    for number in range(5):
        (corpus / f"good-{number}.txt").write_text(f"value {number}", encoding="utf-8")
    (corpus / "bad.docx").write_bytes(b"unsupported")
    (corpus / "empty.txt").touch()
    result = register_paths([corpus], settings, registry)
    assert len(result.outcomes) == 7
    assert [item.input_index for item in result.outcomes] == list(range(7))
    assert result.run.processed == 5 and result.run.failed == 2
    assert result.run.status == "completed_with_errors"
    assert result.run.finished_at >= result.run.started_at
    assert len(registry.list_documents()) == 5


def test_two_valid_one_invalid_directory(corpus, settings, registry):
    (corpus / "one.md").write_text("one", encoding="utf-8")
    (corpus / "two.htm").write_text("<p>two</p>", encoding="utf-8")
    (corpus / "three.exe").write_bytes(b"MZ")
    result = register_paths([corpus], settings, registry)
    assert (result.run.processed, result.run.failed) == (2, 1)


def test_metadata_is_preserved_and_sensitive_url_parts_removed(corpus, settings, registry, monkeypatch):
    marker = "key-" + corpus.parent.name
    monkeypatch.setenv("OPENAI_API_KEY", marker)
    source = corpus / "source.markdown"
    source.write_bytes(b"Untrusted document text does not become instructions.")
    metadata = RegistrationMetadata(
        title=" Kafka docs ", technology=" Kafka ", category="Messaging",
        version_label="3.9", license="Apache-2.0",
        source_url=f"https://user:{marker}@example.org/docs?api_key={marker}#private",
    )
    result = register_paths([source], settings, registry, metadata=metadata)
    record = registry.get_document(result.outcomes[0].result.document_id)
    assert record.title == "Kafka docs" and record.technology == "Kafka"
    assert record.category == "Messaging" and record.version_label == "3.9"
    assert record.license == "Apache-2.0" and record.source_url == "https://example.org/docs"
    assert marker not in record.model_dump_json()
    assert marker.encode() not in registry.path.read_bytes()
    from langchain_core.documents import Document
    framework_document = Document(page_content="", metadata=record.model_dump())
    assert framework_document.metadata["document_id"] == record.document_id
    assert framework_document.metadata["license"] == "Apache-2.0"
    assert framework_document.metadata["raw_hash"] == record.raw_hash
    assert framework_document.metadata["content_hash"] is None


def test_latin1_and_image_only_pdf_are_registered_without_extraction(corpus, settings, registry, pdf_factory):
    (corpus / "latin.txt").write_bytes("caf\u00e9".encode("latin-1"))
    (corpus / "image.pdf").write_bytes(pdf_factory(image_only=True))
    result = register_paths([corpus], settings, registry)
    assert result.run.processed == 2
    assert all(item.result.status == "registered" for item in result.outcomes)


def test_nested_and_empty_directories_are_explicit_failures(corpus, settings, registry):
    subdirectory = corpus / "nested"
    subdirectory.mkdir()
    (subdirectory / "hidden.txt").write_text("not recursively registered", encoding="utf-8")
    nested = register_paths([corpus], settings, registry)
    assert nested.run.failed == 1
    assert nested.outcomes[0].error.code == "SOURCE_NOT_ACCESSIBLE"
    empty = corpus / "empty"
    empty.mkdir()
    assert register_paths([empty], settings, registry).outcomes[0].error.code == "EMPTY_DIRECTORY"
