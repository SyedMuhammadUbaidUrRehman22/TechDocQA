"""Structure preservation around LangChain's local HTML loader; no fetching."""

import hashlib
import codecs
from email.message import Message
from importlib.metadata import version
from pathlib import Path
import re
from uuid import uuid4

from bs4 import BeautifulSoup
# shortcut: pinned archived framework loader, replace when a maintained HTML integration is selected.
from langchain_community.document_loaders.html_bs import BSHTMLLoader

from techdocqa.errors import TechDocQAError
from techdocqa.privacy import safe_text

EXTRACTION_POLICY = "html-structure-v1"


def extract_html(raw: bytes, directory: Path, minimum: int, content_type_header: str = "text/html") -> dict:
    headers = Message()
    headers["Content-Type"] = content_type_header
    encoding = headers.get_content_charset()
    try:
        if encoding:
            encoding = codecs.lookup(encoding).name
            decoded = raw.decode(encoding)
        else:
            decoded = raw
        soup = BeautifulSoup(decoded, "html.parser")
    except (LookupError, UnicodeError, TypeError):
        raise TechDocQAError("DECODE_FAILED", "HTML encoding could not be decoded safely.", stage="extraction") from None
    if soup.contains_replacement_characters or "\x00" in soup.get_text():
        raise TechDocQAError("DECODE_FAILED", "HTML text could not be decoded safely.", stage="extraction")
    if soup.body is None or soup.find(["p", "pre", "h1", "h2", "article", "main"]) is None:
        raise TechDocQAError("MALFORMED_HTML", "A usable HTML document body is required.", stage="extraction")
    warnings = []
    titles = soup.find_all("title")
    title = None
    if len(titles) == 1 and not titles[0].find(True):
        title = safe_text(titles[0].get_text()) or None
        if title is not None and len(title) > 1000:
            title = None
    if title is None:
        warnings.append("MISSING_OR_INVALID_TITLE")
    encoding = encoding or soup.original_encoding
    for element in list(soup.select("script, style, nav, header, footer, aside, form, button, [role=navigation], [role=banner], [role=dialog]")):
        element.decompose()
    for element in list(soup.select('[id*="cookie" i], [class*="cookie" i], [id*="banner" i], [class*="cookie-consent" i]')):
        element.decompose()
    root = soup.find("main") or soup.find("article") or soup.body
    if root is None:
        raise TechDocQAError("NO_TEXT_EXTRACTED", "HTML has no usable documentation body.", stage="extraction")
    headings = []
    hierarchy = []
    for heading in root.find_all(re.compile(r"^h[1-6]$")):
        level = int(heading.name[1])
        text = heading.get_text()
        hierarchy = [(depth, value) for depth, value in hierarchy if depth < level]
        hierarchy.append((level, text))
        headings.append({"level": level, "text": safe_text(text),
                         "section_path": [safe_text(value) for _, value in hierarchy]})
        heading.insert_before("\n" + "#" * level + " ")
        heading.insert_after("\n")
    # Protect decoded code text from BeautifulSoup's separator/whitespace handling.
    token_prefix = uuid4().hex
    protected = {}
    for element in list(root.select("pre, code")):
        if element.parent is None:
            continue
        value = element.get_text()
        token = f"TECHDOCQA{token_prefix}{len(protected)}END"
        protected[token] = (value, "block" if element.name == "pre" else "inline")
        element.replace_with(token)
    for element in root.select("p, li, tr, div, section, dl"):
        element.insert_after("\n")
    for element in root.select("td, th"):
        element.insert_after("\t")
    for element in root.select("br"):
        element.replace_with("\n")
    cleaned = directory / "cleaned.html"
    cleaned.write_text(str(root), encoding="utf-8")
    document = BSHTMLLoader(str(cleaned), open_encoding="utf-8",
                            bs_kwargs={"features": "html.parser"}, get_text_separator="").load()[0]
    parts = []
    code_spans = []
    cursor = length = 0
    for match in re.finditer(f"TECHDOCQA{token_prefix}[0-9]+END", document.page_content):
        before = document.page_content[cursor:match.start()]
        parts.append(before)
        length += len(before)
        value, kind = protected[match.group()]
        padding = "\n\n" if kind == "block" else ""
        parts.extend([padding, value, padding])
        code_spans.append({"kind": kind, "start": length + len(padding), "end": length + len(padding) + len(value)})
        length += len(value) + 2 * len(padding)
        cursor = match.end()
    parts.append(document.page_content[cursor:])
    text = "".join(parts)
    if sum(not character.isspace() for character in text) < minimum:
        raise TechDocQAError("NO_TEXT_EXTRACTED", "HTML contains too little usable text.", stage="extraction")
    (directory / "extracted.txt").write_bytes(text.encode("utf-8"))
    return {"original_title": title, "encoding": encoding, "headings": headings,
            "code_spans": code_spans,
            "extraction_dependencies": {name: version(name) for name in ("langchain-community", "langchain-core", "beautifulsoup4", "soupsieve")},
            "warnings": warnings, "extraction_policy": EXTRACTION_POLICY,
            "extracted_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}
