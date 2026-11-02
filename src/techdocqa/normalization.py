"""Offline, code-preserving FR-04 normalization. See docs/DECISIONS.md."""

from collections import Counter
import re
import unicodedata

from langchain_core.documents import Document

from techdocqa.errors import TechDocQAError

NORMALIZATION_POLICY = "technical-text-v2"
PAGE_NUMBER = re.compile(r"\s*(?:Page\s+)?\d+\s*")


def code_spans(text: str, explicit: list[dict] | None = None) -> list[dict]:
    """Character offsets into extracted text; unknown/overlapping spans fail closed."""
    spans = []
    if explicit is not None and (not isinstance(explicit, list) or any(not isinstance(span, dict) for span in explicit)):
        raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "Code boundaries are invalid.", stage="normalization")
    for span in explicit or []:
        start, end, kind = span.get("start"), span.get("end"), span.get("kind")
        if (type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text)
                or kind not in {"inline", "block"}):
            raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "Code boundaries are invalid.", stage="normalization")
        if start != end:
            spans.append({"start": start, "end": end, "kind": kind})
    spans.sort(key=lambda span: span["start"])
    if any(left["end"] > right["start"] for left, right in zip(spans, spans[1:])):
        raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "Code boundaries overlap.", stage="normalization")
    # Explicit HTML boundaries are authoritative; Markdown-looking code inside them is data.
    if explicit is not None:
        return spans
    fence = None
    offset = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                spans.append({"start": fence[2], "end": offset + len(line), "kind": "block"})
                fence = None
        elif marker:
            fence = (marker[1][0], len(marker[1]), offset)
        elif line.startswith(("    ", "\t")):
            spans.append({"start": offset, "end": offset + len(line), "kind": "block"})
        else:
            for match in re.finditer(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", line):
                spans.append({"start": offset + match.start(), "end": offset + match.end(), "kind": "inline"})
        offset += len(line)
    if fence:
        spans.append({"start": fence[2], "end": len(text), "kind": "block"})
    return sorted(spans, key=lambda span: span["start"])


def headings(text: str, spans: list[dict]) -> list[dict]:
    result, hierarchy = [], []
    offset = 0
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
        if match and not any(span["start"] <= offset < span["end"] for span in spans):
            level, title = len(match[1]), match[2]
            hierarchy = [(depth, value) for depth, value in hierarchy if depth < level]
            hierarchy.append((level, title))
            result.append({"level": level, "text": title, "section_path": [value for _, value in hierarchy],
                           "start": offset})
        offset += len(line)
    return result


def strip_page_furniture(pages: list[tuple[list[str], str]], *, repeated_lines: bool):
    """Blank page numbers and repeated lines at page edges, peeling inward until stable.

    Only edges qualify: a standalone number or repeated line in a page body is content.
    Lines holding a code placeholder are never removed and stop peeling on that side.
    """
    def edges(lines):
        nonempty = [i for i, line in enumerate(lines) if line.strip()]
        return set(nonempty[:1] + nonempty[-1:])

    def key(line):
        return unicodedata.normalize("NFC", " ".join(line.split()))

    while True:
        changed = False
        for lines, sentinel in pages:
            numbers = [i for i in edges(lines) if sentinel not in lines[i] and PAGE_NUMBER.fullmatch(lines[i])]
            while numbers:
                changed = True
                for i in numbers:
                    lines[i] = ""
                numbers = [i for i in edges(lines) if sentinel not in lines[i] and PAGE_NUMBER.fullmatch(lines[i])]
        counts = Counter()
        if repeated_lines:
            for lines, sentinel in pages:
                if sum(1 for line in lines if line.strip() and sentinel not in line) >= 3:
                    counts.update({key(lines[i]) for i in edges(lines) if sentinel not in lines[i]})
        repeated = {line for line, count in counts.items() if count * 2 >= len(pages)}
        for lines, sentinel in pages:
            for i in edges(lines):
                if sentinel not in lines[i] and key(lines[i]) in repeated:
                    lines[i] = ""
                    changed = True
        if not changed:
            return


def normalize_documents(documents: list[Document], *, minimum: int = 1) -> list[Document]:
    if not documents or any(not isinstance(doc, Document) or not isinstance(doc.page_content, str) for doc in documents):
        raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "Extracted documents are invalid.", stage="normalization")
    protected = []
    for document in documents:
        text = document.page_content
        if any((ord(char) < 32 and char not in "\t\r\n\f") or 0x7f <= ord(char) < 0xa0
               or 0xd800 <= ord(char) <= 0xdfff or char == "\ufffd" for char in text):
            raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "Extracted text contains invalid characters.", stage="normalization")
        protected.append(code_spans(text, document.metadata.get("code_spans")))
    vocabulary = set()
    for document, spans in zip(documents, protected, strict=True):
        cursor = 0
        for span in spans:
            vocabulary.update(re.findall(r"\b[a-zA-Z]+\b", document.page_content[cursor:span["start"]]))
            cursor = span["end"]
        vocabulary.update(re.findall(r"\b[a-zA-Z]+\b", document.page_content[cursor:]))
    prepared = []
    for document, spans in zip(documents, protected, strict=True):
        text = document.page_content
        # Private-use sentinels are selected outside the input and removed before output.
        sentinel = "\ue000"
        while sentinel in text:
            sentinel += "\ue000"
        values = []
        parts, cursor = [], 0
        for span in spans:
            parts.extend([text[cursor:span["start"]], f"{sentinel}{len(values)}{sentinel}"])
            values.append((text[span["start"]:span["end"]], span["kind"]))
            cursor = span["end"]
        parts.append(text[cursor:])
        prose = unicodedata.normalize("NFC", "".join(parts).replace("\r\n", "\n").replace("\r", "\n"))
        prepared.append((document, prose.split("\n"), sentinel, values))
    pages = [(lines, sentinel) for document, lines, sentinel, _ in prepared if "page" in document.metadata]
    strip_page_furniture(pages, repeated_lines=len(documents) >= 3 and len(pages) == len(documents))
    normalized = []
    for document, lines, sentinel, values in prepared:
        for i, line in enumerate(lines):
            indent = re.match(r"[ \t]*", line)[0]
            body = re.sub(r"[ \t]+", " ", line[len(indent):]).rstrip(" ")
            hard_break = "  " if document.metadata.get("doc_type") == "md" and body and line.endswith("  ") else ""
            lines[i] = indent + body + hard_break if body else ""
        prose = re.sub(r"\n{4,}", "\n\n\n", "\n".join(lines)).strip("\n")
        prose = re.sub(r"(?<![\w./\\:-])([a-zA-Z]+)-\n([a-zA-Z]+)\b",
                       lambda m: m[1] + m[2] if m[1] + m[2] in vocabulary else m[0], prose)
        parts, output_spans, cursor, length = [], [], 0, 0
        for match in re.finditer(re.escape(sentinel) + r"(\d+)" + re.escape(sentinel), prose):
            before = prose[cursor:match.start()]
            value, kind = values[int(match[1])]
            parts.extend([before, value])
            length += len(before)
            output_spans.append({"start": length, "end": length + len(value), "kind": kind})
            length += len(value)
            cursor = match.end()
        parts.append(prose[cursor:])
        output = "".join(parts)
        # A leading "#" is only heading syntax in Markdown and the markers inserted for HTML.
        plain = document.metadata.get("doc_type") in {"txt", "pdf"} or "page" in document.metadata
        metadata = {**document.metadata, "code_spans": output_spans,
                    "headings": [] if plain else headings(output, output_spans), "normalization_policy": NORMALIZATION_POLICY}
        normalized.append(Document(page_content=output, metadata=metadata))
    if sum(not char.isspace() for doc in normalized for char in doc.page_content) < minimum:
        raise TechDocQAError("NO_TEXT_EXTRACTED", "Document contains too little usable text.", stage="normalization")
    return normalized


def document_text(documents: list[Document]) -> str:
    """Hash representation: page texts in order, separated by two LF characters."""
    return "\n\n".join(document.page_content for document in documents)
