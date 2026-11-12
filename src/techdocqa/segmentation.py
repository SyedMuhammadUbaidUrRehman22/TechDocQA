"""Deterministic sentence spans into unchanged normalized text (FR-06).

Two policies share one output contract: half-open offsets that cover every character, so concatenating the spans
reproduces the text (AC-06.3), with each span's trailing whitespace kept in it. "rules" is the P0 policy and the
default. "spacy" is the FR-06 P1 policy (P9-2): spaCy's tokenizer and rule-based sentencizer, corrected by technical
rules. It needs the nlp extra and no model download. Which policy chunking uses is a chunking setting, so changing it
re-chunks every document.
"""

from bisect import bisect_right
from functools import lru_cache
import re

from techdocqa.errors import TechDocQAError
from techdocqa.normalization import code_spans

SEGMENTATION_POLICY = "technical-sentences-v4"
SPACY_POLICY = "spacy-technical-sentences-v2"
POLICIES = {"rules": SEGMENTATION_POLICY, "spacy": SPACY_POLICY}
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
        if (match[0][0] == "." and not re.search(r"\n[ \t]*\n", match[0])
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


# The spaCy policy's technical rules, applied to the sentencizer's proposals:
# 1. A paragraph break (a blank line) is a boundary, and so is a line that starts with a list marker.
# 2. A boundary needs whitespace before it, so "System.Console" or "end.Next" never splits.
# 3. No boundary after these abbreviations, whatever follows; "etc." ends a sentence only before an uppercase letter.
# 4. Opening quotes and brackets that the sentencizer leaves at the end of a sentence move to the next one.
# 5. No boundary inside protected code.
NEVER_FINAL = frozenset("e.g i.e vs cf fig figs eq eqs no nos vol vols approx al resp dr mr mrs ms prof st sec ch pp".split())
SOMETIMES_FINAL = frozenset({"etc"})
OPENING = frozenset({'"', "'", "“", "‘", "(", "["})
CLOSING = frozenset({'"', "'", "”", "’", ")", "]"})
PARAGRAPH = re.compile(r"\n[ \t]*\n+")
LIST_ITEM = re.compile(r"(?m)^[ \t]*(?:[-*+•]|\d{1,3}[.)])[ \t]+(?=\S)")


def spacy_version() -> str | None:
    try:
        from importlib.metadata import version
        import spacy  # noqa: F401
        return version("spacy")
    except Exception:
        return None


@lru_cache(maxsize=1)
def spacy_pipeline():
    """A blank English pipeline with the rule-based sentencizer: no model, no download, deterministic."""
    try:
        import spacy
    except ImportError:
        raise TechDocQAError("SEGMENTER_UNAVAILABLE", "The spaCy segmentation policy needs the nlp extra.", stage="configuration") from None
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    return nlp


def accepted(doc, index: int) -> int | None:
    """The corrected start token of a proposed sentence start, or None when the technical rules reject it.

    Scans back from the proposal only, so a long paragraph costs time linear in its tokens."""
    start = index
    # After a single line break spaCy starts the sentence at the newline token; the sentence starts at the next word.
    while start < len(doc) and doc[start].is_space:
        start += 1
    if start == len(doc):
        return None
    # Rule 4: an opening quote or bracket directly before the next word, after whitespace, belongs to that sentence.
    while (start - 1 > 0 and doc[start - 1].text in OPENING and not doc[start - 1].whitespace_
           and (doc[start - 2].whitespace_ or doc[start - 2].is_space)):
        start -= 1
    # Rule 2: whitespace before the boundary.
    if not doc[start - 1].whitespace_ and not doc[start - 1].is_space:
        return None
    # Rule 3: the word before the final period, past any closing quotes or brackets.
    k = start - 1
    while k >= 0 and doc[k].is_space:
        k -= 1
    while k >= 0 and doc[k].text in CLOSING:
        k -= 1
    if k >= 1 and doc[k].text == "." and not doc[k - 1].whitespace_:
        word = doc[k - 1].text.casefold().rstrip(".")
        if word in NEVER_FINAL or (word in SOMETIMES_FINAL and not doc[start].text[:1].isupper()):
            return None
    return start


def spacy_sentence_spans(text: str, protected: list[dict] | None = None) -> list[dict]:
    """FR-06 P1: the same coverage contract as sentence_spans, from spaCy's sentencizer and the technical rules."""
    spans = code_spans(text, protected)
    if not text:
        return []
    nlp = spacy_pipeline()
    starts = [span["start"] for span in spans]

    def inside_code(position: int) -> bool:
        index = bisect_right(starts, position) - 1
        return index >= 0 and spans[index]["start"] < position < spans[index]["end"]

    boundaries = set()
    regions, cursor = [], 0
    for match in PARAGRAPH.finditer(text):
        regions.append((cursor, match.start()))
        cursor = match.end()
        boundaries.add(cursor)
    regions.append((cursor, len(text)))
    boundaries |= {match.start() for match in LIST_ITEM.finditer(text)}
    for begin, end in regions:
        if not text[begin:end].strip():
            continue
        nlp.max_length = max(nlp.max_length, end - begin + 1)
        doc = nlp(text[begin:end])
        for sentence in list(doc.sents)[1:]:
            start = accepted(doc, sentence.start)
            if start is not None:
                boundaries.add(begin + doc[start].idx)
    cuts = sorted(position for position in boundaries if 0 < position < len(text) and not inside_code(position))
    edges = [0, *cuts, len(text)]
    return [{"start": start, "end": end} for start, end in zip(edges, edges[1:]) if start < end]


def segmenter(name: str):
    """The span function for a segmentation setting."""
    if name == "spacy":
        spacy_pipeline()
        return spacy_sentence_spans
    if name == "rules":
        return sentence_spans
    raise TechDocQAError("INVALID_CONFIGURATION", "Unknown segmentation policy.", stage="configuration")
