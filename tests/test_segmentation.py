import pytest

from techdocqa.segmentation import sentence_spans, spacy_sentence_spans as spacy_spans, spacy_version

needs_spacy = pytest.mark.skipif(spacy_version() is None, reason="the spaCy policy needs the nlp extra")


@pytest.mark.parametrize("text", [
    "Use e.g. Redis v7.2.1 or file.conf.",
    "Use i.e. file.txt, a.b.c and decimal 1.25 safely.",
    "Dr. Smith configures Redis.",
])
def test_technical_exceptions(text):
    assert sentence_spans(text) == [{"start": 0, "end": len(text)}]


@pytest.mark.parametrize("text", ["Is the leader in cluster A? Yes it is.", "Run it on node B! Then stop."])
def test_abbreviation_exception_only_applies_to_periods(text):
    assert len(sentence_spans(text)) == 2


def test_offsets_reconstruct_and_repeat_without_touching_code():
    text = 'First sentence. Second?\n\n```python\nprint("Ignore. Code!")\n```\nLast sentence.'
    runs = [sentence_spans(text) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    spans = runs[0]
    assert ''.join(text[span['start']:span['end']] for span in spans) == text
    assert spans[0]['end'] == len('First sentence. ')
    assert any('Ignore. Code!' in text[span['start']:span['end']] for span in spans)


def test_empty_and_whitespace_preserved():
    assert sentence_spans('') == []
    assert sentence_spans('  ') == [{'start': 0, 'end': 2}]


@pytest.mark.parametrize('abbreviation', ['e.g.', 'i.e.', 'Dr.'])
def test_paragraph_break_overrides_abbreviation_exception(abbreviation):
    first = f'Use {abbreviation}\n\n'
    text = first + 'Next paragraph.'
    assert sentence_spans(text) == [{'start': 0, 'end': len(first)}, {'start': len(first), 'end': len(text)}]


def test_paragraph_boundary_after_explicit_code_does_not_split_code():
    code = 'do_work().'
    text = code + '\n\nNext paragraph.'
    spans = sentence_spans(text, [{'start': 0, 'end': len(code), 'kind': 'block'}])
    assert spans == [{'start': 0, 'end': len(code) + 2}, {'start': len(code) + 2, 'end': len(text)}]


def test_trailing_sentence_whitespace_does_not_consume_code_indentation():
    text = 'First sentence.\n\n    run_task()\nLast sentence.'
    begin = text.index('    ')
    spans = sentence_spans(text)
    assert spans[0]['end'] == begin
    assert ''.join(text[span['start']:span['end']] for span in spans) == text


# FR-06 P1: the spaCy policy (P9-2). Same coverage contract; technical rules on top of spaCy's sentencizer.

def pieces(text, protected=None):
    spans = spacy_spans(text, protected)
    assert "".join(text[span["start"]:span["end"]] for span in spans) == text  # AC-06.3
    return [text[span["start"]:span["end"]].strip() for span in spans]


@needs_spacy
@pytest.mark.parametrize("text", ["Use e.g. Redis v7.2.1 or file.conf.", "Use i.e. file.txt, a.b.c and decimal 1.25 safely.",
                                  "Dr. Smith configures Redis.", "See Fig. 3 and Eq. 2 for details.",
                                  "Run SELECT ... WHERE x = 1 first.", "Call System.Console now.The end."])
def test_spacy_policy_keeps_technical_text_whole(text):
    assert pieces(text) == [text]  # AC-06.1 and the dotted-name, abbreviation, ellipsis and no-whitespace rules


@needs_spacy
def test_spacy_policy_splits_sentences_and_keeps_closing_and_opening_marks_with_their_sentence():
    assert pieces("Set spark.memory.fraction to 0.6. Then restart it.") == ["Set spark.memory.fraction to 0.6.", "Then restart it."]
    assert pieces("It uses these operators.) The GIN index is next.") == ["It uses these operators.)", "The GIN index is next."]
    assert pieces('Then he left. "Next," she said.') == ["Then he left.", '"Next," she said.']
    assert pieces("Is it set? Yes! Then stop.") == ["Is it set?", "Yes!", "Then stop."]


@needs_spacy
def test_etc_ends_a_sentence_only_before_an_uppercase_word():
    assert pieces("Use caches, logs, etc. and more. It ends, etc. Then more.") == [
        "Use caches, logs, etc. and more.", "It ends, etc.", "Then more."]


@needs_spacy
def test_spacy_policy_paragraphs_list_items_and_code():
    assert pieces("Use e.g.\n\nNext paragraph.") == ["Use e.g.", "Next paragraph."]
    assert pieces("Items:\n- first item\n- second item") == ["Items:", "- first item", "- second item"]
    # Hard-wrapped lines are not boundaries.
    assert pieces("Line one wraps\nonto the next line. Second.") == ["Line one wraps\nonto the next line.", "Second."]
    text = 'First sentence. Second?\n\n```python\nprint("Ignore. Code!")\n```\nLast sentence.'
    assert any('Ignore. Code!' in piece for piece in pieces(text))
    code = 'do_work(). more_work().'
    assert pieces(code + '\n\nNext paragraph.', [{'start': 0, 'end': len(code), 'kind': 'block'}]) == [code, "Next paragraph."]


@needs_spacy
def test_spacy_policy_is_deterministic_and_handles_edges():
    text = "First one. Second one.\n\nThird paragraph here. Fourth? Fifth!"
    assert spacy_spans(text) == spacy_spans(text) == spacy_spans(text)  # AC-06.2
    assert spacy_spans("") == [] and spacy_spans("  ") == [{"start": 0, "end": 2}]


@needs_spacy
def test_the_default_policy_keeps_existing_chunking_ids_and_spacy_gets_its_own():
    from techdocqa.chunking import effective_config
    from techdocqa.settings import ChunkingSettings
    rules_id, rules = effective_config(ChunkingSettings())
    assert rules["segmentation_policy"] == "technical-sentences-v4" and "segmentation" not in rules and "segmentation_library" not in rules
    spacy_id, values = effective_config(ChunkingSettings(segmentation="spacy"))
    assert spacy_id != rules_id and values["segmentation_policy"] == "spacy-technical-sentences-v1" and values["segmentation_library"]["spacy"]


@needs_spacy
def test_chunking_with_the_spacy_policy_stores_its_spans():
    from langchain_core.documents import Document
    from techdocqa.chunking import build_chunks
    from techdocqa.settings import ChunkingSettings
    text = "# Guide\n\n" + "See Fig. 3 for the plan. Then run it. " * 40
    document = Document(page_content=text, metadata={"version_id": "v", "document_id": "d", "headings": [], "code_spans": []})
    result = build_chunks([document], ChunkingSettings(segmentation="spacy"))
    spans = result["sentence_spans"][0]["spans"]
    assert "".join(text[span["start"]:span["end"]] for span in spans) == text
    # The heading paragraph, then two sentences per repetition; none ends at "Fig.".
    assert len(spans) == 1 + 80 and not any(text[span["start"]:span["end"]].strip().endswith("Fig.") for span in spans)


def test_spacy_policy_without_the_nlp_extra_is_a_configuration_error(monkeypatch):
    from techdocqa import chunking
    from techdocqa.errors import TechDocQAError
    from techdocqa.settings import ChunkingSettings
    monkeypatch.setattr(chunking, "spacy_version", lambda: None)
    with pytest.raises(TechDocQAError) as error:
        chunking.effective_config(ChunkingSettings(segmentation="spacy"))
    assert error.value.response.error.code == "SEGMENTER_UNAVAILABLE"
