"""Deterministic sentence spans into unchanged normalized text (FR-06 P0)."""

from bisect import bisect_right
import re

from techdocqa.normalization import code_spans

SEGMENTATION_POLICY = "technical-sentences-v3"
BOUNDARY = re.compile(r"\n[ \t]*\n+|[.!?][\"')\]]*(?:[ \t\r\n]+|$)")
ABBREVIATION = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|Mr|Mrs|Dr|Prof)|\b[A-Za-z])$", re.IGNORECASE)


def sentence_spans(text: str, protected: list[dict] | None = None) -> list[dict]:
    """Half-open offsets cover every character, including intervening whitespace."""
    spans = code_spans(text, protected)
    starts = [span["start"] for span in spans]
    result, start = [], 0
    for match in BOUNDARY.finditer(text):
        index = bisect_right(starts, match.start()) - 1
        if index >= 0 and spans[index]["end"] > match.start():
            code_end = spans[index]['end']
            if (match.end() <= code_end
                    or not re.search(r"\n[ \t]*\n", text[max(match.start(), code_end - 1):match.end()])):
                continue
        if (not re.search(r"\n[ \t]*\n", match[0])
                and ABBREVIATION.search(text[max(0, match.start() - 30):match.start()])):
            continue
        end = match.end()
        end_index = bisect_right(starts, end) - 1
        if end_index >= 0 and spans[end_index]['start'] < end < spans[end_index]['end']:
            end = spans[end_index]['start']
        result.append({"start": start, "end": end})
        start = end
    if start < len(text):
        result.append({"start": start, "end": len(text)})
    return result
