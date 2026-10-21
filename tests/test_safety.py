import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from pypdf import PdfWriter
from io import BytesIO

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion import safety
from techdocqa.ingestion.pipeline import register_paths
from techdocqa.ingestion.safety import validate_file


def error_code(path, settings):
    with pytest.raises(TechDocQAError) as caught:
        validate_file(path, settings)
    return caught.value.response.error.code


def test_outside_paths_traversal_and_sibling_prefixes_are_rejected(corpus, settings):
    outside = corpus.parent / "outside.txt"
    outside.write_bytes(b"private")
    sibling = corpus.parent / (corpus.name + "_other")
    sibling.mkdir()
    (sibling / "one.txt").write_bytes(b"private")
    assert error_code(outside, settings) == "PATH_NOT_ALLOWED"
    assert error_code(corpus / "../outside.txt", settings) == "PATH_NOT_ALLOWED"
    assert error_code(sibling / "one.txt", settings) == "PATH_NOT_ALLOWED"
    assert error_code(corpus.parent / "not-present.txt", settings) == "PATH_NOT_ALLOWED"


@pytest.mark.skipif(os.name != "nt", reason="Windows alternate-drive path")
def test_other_drive_is_disallowed(settings):
    other = "Z:" if Path(settings.allowed_directories[0]).drive.upper() != "Z:" else "Y:"
    assert error_code(Path(other + "/outside.txt"), settings) == "PATH_NOT_ALLOWED"


def test_directories_are_rejected_where_a_file_is_expected(corpus, settings):
    assert error_code(corpus, settings) == "SOURCE_NOT_ACCESSIBLE"


def test_oversize_rejected_before_pdf_inspection(corpus, settings, monkeypatch):
    source = corpus / "large.pdf"
    source.write_bytes(b"%PDF" + b"x" * 20)
    settings.ingestion.max_file_bytes = 10
    def must_not_inspect(*_):
        pytest.fail("oversized input reached PDF inspection")
    monkeypatch.setattr(safety, "pdf_page_count", must_not_inspect)
    assert error_code(source, settings) == "FILE_TOO_LARGE"


def test_exact_byte_limit_is_accepted(corpus, settings):
    source = corpus / "exact.txt"
    source.write_bytes(b"1234567890")
    settings.ingestion.max_file_bytes = 10
    assert validate_file(source, settings).size_bytes == 10


def test_pdf_page_limit_and_malformed_structure(corpus, settings, pdf_factory):
    source = corpus / "pages.pdf"
    source.write_bytes(pdf_factory(pages=2))
    settings.ingestion.max_pages = 1
    assert error_code(source, settings) == "PAGE_LIMIT_EXCEEDED"
    source.write_bytes(b"%PDF-1.7\nnot a PDF structure\n%%EOF")
    assert error_code(source, settings) == "FORMAT_MISMATCH"


def test_pdf_worker_does_not_import_code_from_input_directory(corpus, settings, pdf_factory, monkeypatch):
    source = corpus / "one.pdf"
    source.write_bytes(pdf_factory())
    (corpus / "techdocqa.py").write_text("raise RuntimeError('untrusted module executed')", encoding="utf-8")
    monkeypatch.chdir(corpus)
    assert validate_file(source, settings).page_count == 1


def test_pdf_worker_failure_is_distinct_from_invalid_document(corpus, settings, monkeypatch):
    source = corpus / "one.pdf"
    source.write_bytes(b"%PDF-1.7")
    monkeypatch.setattr(safety.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, b"", b"private diagnostic"))
    assert error_code(source, settings) == "PDF_CHECK_FAILED"


def test_encrypted_pdf_is_rejected_without_decryption(corpus, settings):
    source = corpus / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("not-an-api-secret")
    buffer = BytesIO()
    writer.write(buffer)
    source.write_bytes(buffer.getvalue())
    assert error_code(source, settings) == "PDF_ENCRYPTED"


def test_pdf_deadline_terminates_a_real_worker(corpus, settings, monkeypatch):
    source = corpus / "slow.pdf"
    source.write_bytes(b"%PDF-1.7")
    settings.ingestion.parse_timeout_seconds = 1
    original = subprocess.run
    def sleeping_worker(command, **kwargs):
        assert command[-1] == "techdocqa.ingestion.pdf_check"
        return original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
    monkeypatch.setattr(safety.subprocess, "run", sleeping_worker)
    started = time.monotonic()
    assert error_code(source, settings) == "PARSE_TIMEOUT"
    assert time.monotonic() - started < 5


def test_open_permission_failure_is_safe(corpus, settings, monkeypatch):
    source = corpus / "one.txt"
    source.write_bytes(b"one")
    original = os.open
    def denied(path, *args, **kwargs):
        if Path(path) == source:
            raise PermissionError("private local path must not leak")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(safety.os, "open", denied)
    assert error_code(source, settings) == "SOURCE_NOT_ACCESSIBLE"


def test_replacement_between_validation_and_open_is_detected(corpus, settings, monkeypatch):
    source = corpus / "one.txt"
    source.write_bytes(b"original")
    replacement = corpus / "replacement.txt"
    replacement.write_bytes(b"different inode")
    original = os.open
    swapped = False
    def replace_then_open(path, *args, **kwargs):
        nonlocal swapped
        if Path(path) == source and not swapped:
            swapped = True
            os.replace(replacement, source)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(safety.os, "open", replace_then_open)
    assert error_code(source, settings) == "SOURCE_CHANGED"


def test_symlink_escape_and_internal_alias(corpus, settings, registry):
    outside = corpus.parent / "outside.txt"
    outside.write_bytes(b"private")
    escape = corpus / "escape.txt"
    try:
        escape.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"File symlink creation unavailable: {error.winerror if os.name == 'nt' else error.errno}")
    assert error_code(escape, settings) == "PATH_NOT_ALLOWED"
    source = corpus / "one.txt"
    source.write_bytes(b"inside")
    alias = corpus / "alias.txt"
    alias.symlink_to(source)
    result = register_paths([source, alias], settings, registry)
    assert result.run.processed == 1 and result.run.skipped == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junctions")
def test_windows_junction_escape_is_rejected(corpus, settings):
    outside = corpus.parent / "private"
    outside.mkdir()
    (outside / "one.txt").write_bytes(b"private")
    junction = corpus / "junction"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
    assert result.returncode == 0
    assert error_code(junction / "one.txt", settings) == "PATH_NOT_ALLOWED"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junctions")
def test_swapped_allowlisted_root_does_not_authorize_a_new_tree(corpus, settings):
    outside = corpus.parent / "private"
    outside.mkdir()
    (outside / "one.txt").write_bytes(b"private")
    corpus.rmdir()
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(corpus), str(outside)], capture_output=True)
    assert result.returncode == 0
    assert error_code(corpus / "one.txt", settings) == "PATH_NOT_ALLOWED"


def test_empty_effective_allowlist_fails_closed(corpus, settings):
    source = corpus / "one.txt"
    source.write_bytes(b"one")
    settings.allowed_directories = []
    assert error_code(source, settings) == "INVALID_CONFIGURATION"


def test_missing_allowed_root_is_not_created(settings, registry, corpus):
    missing = corpus / "not-created"
    settings.allowed_directories = [str(missing)]
    result = register_paths([missing / "one.txt"], settings, registry)
    assert result.outcomes[0].error.code == "SOURCE_NOT_ACCESSIBLE"
    assert not missing.exists()


def test_failure_messages_are_sanitized_before_persistence(registry, corpus):
    marker = "secret-" + corpus.parent.name
    run_id, attempts = registry.start_run(1)
    error = TechDocQAError("SOURCE_NOT_ACCESSIBLE", f"https://user:password@example.org/file?api_key={marker}").response.error
    registry.fail_attempt(attempts[0], error)
    registry.finish_run(run_id)
    assert marker not in registry.get_run(run_id).model_dump_json()
    assert marker.encode() not in registry.path.read_bytes()
