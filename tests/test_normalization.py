import copy
import hashlib

from langchain_core.documents import Document
import pytest

from techdocqa.errors import TechDocQAError
from techdocqa.normalization import document_text, normalize_documents


def normalize(text, **metadata):
    return normalize_documents([Document(page_content=text, metadata=metadata)])[0]


def test_line_endings_unicode_whitespace_and_stable_utf8_hash():
    first = normalize("\r\n# Cafe\u0301\r\n\r\nconsumer.group  and\tmax.poll.interval.ms \r\n\r\n\r\n\r\nSQL\r\n")
    second = normalize("\n# Caf\u00e9\n\nconsumer.group and max.poll.interval.ms\n\n\nSQL\n")
    assert first.page_content == second.page_content == "# Caf\u00e9\n\nconsumer.group and max.poll.interval.ms\n\n\nSQL"
    assert hashlib.sha256(first.page_content.encode("utf-8")).hexdigest() == hashlib.sha256(second.page_content.encode("utf-8")).hexdigest()


def test_markdown_hierarchy_code_python_sql_commands_and_case_are_exact():
    code = ("```python\r\nif dag_id == 'Cafe\u0301':\r\n    airflow = {'consumer.group': 2}\r\n\r\n\r\n\r\n"
            "    print(airflow)\r\n```\r\n")
    sql = "~~~sql\nCREATE TABLE events (id INT CHECK (id >= 1 AND id <> 2));\n~~~\n"
    text = ("# Intro\n## Setup\n### Install\nUse `max.poll.interval.ms  =  3` and ``a ` b``.\n\n" + code + sql
            + "    if dag_id:\n        print('C++ HTTP/2 std::vector<int>')\n"
            + "airflow tasks test --local --dag-id=consumer.group C:\\docs\\config.yml /etc/kafka/v1.2.3\n")
    document = normalize(text, doc_type="md")
    assert code in document.page_content and sql in document.page_content
    assert "`max.poll.interval.ms  =  3`" in document.page_content and "``a ` b``" in document.page_content
    assert "    if dag_id:\n        print('C++ HTTP/2 std::vector<int>')\n" in document.page_content
    assert "airflow tasks test --local --dag-id=consumer.group C:\\docs\\config.yml /etc/kafka/v1.2.3" in document.page_content
    assert document.metadata["headings"][2]["section_path"] == ["Intro", "Setup", "Install"]
    assert normalize_documents([document]) == [document]


def test_explicit_html_code_spans_survive_changed_offsets():
    text = "Cafe\u0301  text\r\n\n  config = 'Cafe\u0301'\r\n    dag_id = 1\n\nmax.poll.interval.ms  tail"
    start = text.index("  config")
    end = text.index("\n\nmax")
    spans = [{"start": start, "end": end, "kind": "block"},
             {"start": text.index("max.poll"), "end": text.index("  tail"), "kind": "inline"}]
    result = normalize(text, code_spans=spans)
    assert "Caf\u00e9 text\n" in result.page_content
    assert result.page_content[result.metadata["code_spans"][0]["start"]:result.metadata["code_spans"][0]["end"]] == text[start:end]
    assert normalize_documents([result]) == [result]


@pytest.mark.parametrize("text", ["", " \t\r\n", "\x00text", "bad\ufffd", "bad\ud800", "bad\x80"])
def test_empty_and_malformed_content_is_structured(text):
    with pytest.raises(TechDocQAError) as caught:
        normalize(text)
    assert caught.value.response.error.code in {"NO_TEXT_EXTRACTED", "INVALID_EXTRACTED_CONTENT"}


@pytest.mark.parametrize("spans", [[{"start": -1, "end": 2, "kind": "block"}],
                                  [{"start": 0, "end": 30, "kind": "inline"}],
                                  [{"start": 0, "end": 2, "kind": "wrong"}],
                                  [{"start": 0, "end": 2, "kind": "block"}, {"start": 1, "end": 3, "kind": "inline"}],
                                  ["invalid"], "invalid"])
def test_invalid_code_boundaries_fail_closed(spans):
    with pytest.raises(TechDocQAError) as caught:
        normalize("content", code_spans=spans)
    assert caught.value.response.error.code == "INVALID_EXTRACTED_CONTENT"


def test_unclosed_fence_and_sentinel_input_are_preserved():
    text = "\ue000  prose\n```python\n    dag_id = 'Cafe\u0301'\r\n"
    result = normalize(text)
    assert "\ue000 prose\n" in result.page_content
    assert "```python\n    dag_id = 'Cafe\u0301'\r\n" in result.page_content


def test_markdown_hard_breaks_lists_and_heading_looking_code():
    result = normalize("# Intro\ntext  \n- first\n  - second\n```\n# Not a heading\n```\n", doc_type="md")
    assert "text  \n- first\n  - second" in result.page_content
    assert len(result.metadata["headings"]) == 1


def test_pdf_repeated_edges_and_page_numbers_preserve_body_and_pages():
    documents = [Document(page_content=f"Manual header\nUnique body {i}: consumer.group >= 2\n{i}\nManual footer",
                          metadata={"page": i, "page_index": i - 1, "total_pages": 10}) for i in range(1, 11)]
    output = normalize_documents(documents)
    assert all("Manual" not in doc.page_content and doc.page_content == f"Unique body {i}: consumer.group >= 2"
               for i, doc in enumerate(output, 1))
    assert output[2].metadata["page"] == 3 and output[2].metadata["page_index"] == 2
    assert normalize_documents(output) == output


def test_pdf_does_not_remove_repeated_body_or_short_document_lines():
    documents = [Document(page_content="Repeated sentence", metadata={"page": i}) for i in range(1, 4)]
    assert [doc.page_content for doc in normalize_documents(documents)] == ["Repeated sentence"] * 3
    assert "Header" in normalize_documents([Document(page_content="Header\nBody\nFooter", metadata={"page": 1})])[0].page_content


def test_hyphenation_uses_document_vocabulary_and_leaves_unknown_compounds():
    result = normalize("consumer uses consum-\ner. key-value and unknown-\nword.")
    assert result.page_content == "consumer uses consumer. key-value and unknown-\nword."
    pages = normalize_documents([Document(page_content="consum-\ner", metadata={"page": 1}),
                                 Document(page_content="consumer", metadata={"page": 2})])
    assert [doc.page_content for doc in pages] == ["consumer", "consumer"]
    technical = "consumer maxpoll\n--max-\npoll /consum-\ner C:\\consum-\ner config.consum-\ner"
    assert normalize(technical).page_content == technical


def test_metadata_preservation_determinism_and_no_mutation():
    document = Document(page_content="# Kafka  settings\nUse consumer.group. ", metadata={
        "document_id": "doc_synthetic", "source_url": "https://example.org/docs", "version_label": "4.3",
        "page_fragment": "consumer", "license": None})
    original = copy.deepcopy(document)
    output = [normalize_documents([document]) for _ in range(3)]
    assert output[0] == output[1] == output[2]
    assert document == original
    assert all(output[0][0].metadata[key] == value for key, value in original.metadata.items())
    assert document_text(output[0]) == output[0][0].page_content
