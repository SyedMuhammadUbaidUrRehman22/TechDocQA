import pytest

from techdocqa.segmentation import sentence_spans


@pytest.mark.parametrize("text", [
    "Use e.g. Redis v7.2.1 or file.conf.",
    "Use i.e. file.txt, a.b.c and decimal 1.25 safely.",
    "Dr. Smith configures Redis.",
])
def test_technical_exceptions(text):
    assert sentence_spans(text) == [{"start": 0, "end": len(text)}]


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
