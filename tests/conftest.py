from io import BytesIO
import socket

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from techdocqa.registry import Registry
from techdocqa.settings import Settings


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="enable explicit live documentation smoke tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        for item in items:
            if item.get_closest_marker("live"):
                item.add_marker(pytest.mark.skip(reason="live network smoke requires --live"))


@pytest.fixture(autouse=True)
def deny_unexpected_network(request, monkeypatch):
    if request.node.get_closest_marker("live") and request.config.getoption("--live"):
        monkeypatch.delenv("TECHDOCQA_OFFLINE", raising=False)
        return
    def denied(*args, **kwargs):
        raise AssertionError("Unexpected outbound network access in an offline test")
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setenv("TECHDOCQA_OFFLINE", "1")


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "corpus"
    path.mkdir()
    return path


@pytest.fixture
def settings(corpus, tmp_path):
    return Settings(allowed_directories=[str(corpus)], data_directory=str(tmp_path / "runtime"))


@pytest.fixture
def registry(settings):
    from pathlib import Path
    with Registry(Path(settings.data_directory) / "registry.sqlite3") as value:
        yield value


@pytest.fixture
def pdf_factory():
    def make_pdf(pages=1, *, image_only=False):
        writer = PdfWriter()
        for _ in range(pages):
            page = writer.add_blank_page(width=200, height=200)
            content = DecodedStreamObject()
            if image_only:
                content.set_data(b"q 10 0 0 10 0 0 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00 EI Q")
            else:
                font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                         NameObject("/Subtype"): NameObject("/Type1"),
                                         NameObject("/BaseFont"): NameObject("/Helvetica")})
                page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
                content.set_data(b"BT /F1 12 Tf 10 100 Td (Kafka stores events. Redis stores keys. PostgreSQL stores rows.) Tj ET")
            page[NameObject("/Contents")] = content
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    return make_pdf
