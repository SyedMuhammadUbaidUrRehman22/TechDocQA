"""Phase 9 gold data (P9-9): sample and write annotation sheets, then freeze the filled sheets into gold files.

Usage: nlp_gold.py sheets [--force]            write the sheets under data/nlp/ (git-ignored; they hold document text)
       nlp_gold.py freeze --reviewer NAME [--segmentation-only]
                                               validate the filled sheets and write datasets/nlp/*_gold.jsonl
       nlp_gold.py check                       confirm every gold span still matches the corpus and print the hashes

The sheets never show extractor output, so labels are made before the extractor is seen. The registry is opened
read-only, so this tool never migrates it. Gold files hold source keys, positions, hashes, short anchors and labels,
never whole chunks.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets" / "corpus_manifest.json"
GAZETTEER = ROOT / "config" / "gazetteer.toml"
GOLD = ROOT / "datasets" / "nlp"
SHEETS = ROOT / "data" / "nlp"
SEED = "techdocqa-nlp-gold-2026-11-07"
TYPES = ("TECHNOLOGY", "COMPONENT", "CONCEPT", "PROTOCOL", "IDENTIFIER")
ENTITY_CHUNKS_PER_TECHNOLOGY = 5
MIN_CHUNK_CHARACTERS = 400
MAX_CHUNKS_PER_DOCUMENT = 2
KEYTERM_MAX_CHUNKS = 30
KEYTERM_DOCUMENTS = 5
SEGMENTATION_TARGET = 50
PASSAGES_PER_TECHNOLOGY = 5
MIN_PASSAGE_CHARACTERS = 150
MAX_PASSAGE_CHARACTERS = 700
MARK = "\u2016"
ANCHOR = 40
# A draft splitter independent of the P0 rules: end punctuation, whitespace, then an uppercase letter or a quote.
# Claude Code corrects the draft by hand and you review it; it is never the segmenter under test.
NAIVE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")
HARD = re.compile(r"\b(?:e\.g|i\.e|etc|vs|cf)\.|\w\.\w|\d\.\d|\.\.\.|:\s")
TOKEN_SEPARATED = re.compile(r"\w+(?:[./:#+-]+\w+)+")


def normalized(text: str) -> str:
    """The comparison form for labels: NFKC, case-folded, whitespace collapsed (Q-16)."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def order(key: str) -> str:
    return digest(f"{SEED}|{key}")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str):
    raise SystemExit(json.dumps({"result": "failed", "check": message}))


class Corpus:
    """The frozen public reference: manifest, read-only registry, normalized pages and current chunk artifacts."""

    def __init__(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.documents = [d for d in self.manifest["documents"] if d["role"] == "reference" and d["evaluation_included"]]
        registry = ROOT / "data" / "registry.sqlite3"
        self.connection = sqlite3.connect(f"file:{registry.as_posix()}?mode=ro", uri=True)
        self.by_key = {d["source_key"]: d for d in self.documents}

    def pages(self, document) -> list[str]:
        path = ROOT / document["normalized_documents_path"]
        return [page["page_content"] for page in json.loads(path.read_text(encoding="utf-8"))]

    def chunks(self, document) -> list[dict]:
        row = self.connection.execute("SELECT metadata_json,is_active,finalized FROM registrations WHERE version_id=?",
                                      (document["version_id"],)).fetchone()
        if row is None or not row[1] or not row[2]:
            fail(f"{document['source_key']} is not an active finalized version in the registry")
        chunking = json.loads(row[0]).get("chunking")
        if not chunking:
            fail(f"{document['source_key']} has no chunks")
        path = ROOT / "data" / chunking["snapshot_path"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != chunking["snapshot_hash"]:
            fail(f"chunk artifact for {document['source_key']} failed its hash")
        return json.loads(raw)["chunks"]

    def span(self, item) -> str:
        document = self.by_key.get(item["source_key"])
        if document is None:
            fail(f"{item['source_key']} is not in the evaluation scope")
        pages = self.pages(document)
        text = pages[item["document_index"]][item["start"]:item["end"]]
        if digest(text) != item["text_sha256"]:
            fail(f"span {item['id']} no longer matches {item['source_key']}")
        return text


def location(document, chunk) -> dict:
    return {"source_key": document["source_key"], "technology": document["technology"], "format": document["format"],
            "document_index": int(chunk["document_index"]), "start": int(chunk["start"]), "end": int(chunk["end"])}


def ambiguous_aliases() -> list[str]:
    import tomllib
    data = tomllib.loads(GAZETTEER.read_text(encoding="utf-8"))
    return sorted({alias for entry in data["entities"] for alias in entry.get("ambiguous", [])})


def has_ambiguous_use(text: str, aliases: list[str]) -> bool:
    """An ambiguous name inside a longer technical token (kafka-topics.sh) or in a different case (spark, airflow)."""
    inside = [match.span() for match in TOKEN_SEPARATED.finditer(text)]
    for alias in aliases:
        for match in re.finditer(rf"(?i)(?<!\w){re.escape(alias)}(?!\w)", text):
            if match.group() != alias or any(a <= match.start() and match.end() <= b and (b - a) > len(alias) for a, b in inside):
                return True
    return False


def sample_entities(corpus: Corpus) -> list[dict]:
    """5 chunks per technology in seeded hash order, at most 2 per document, at least 400 characters; the first pick
    per technology comes from the chunks with an ambiguous use, so at least 4 of the 20 have one."""
    aliases = ambiguous_aliases()
    chosen = []
    for technology in sorted({d["technology"] for d in corpus.documents}):
        pool = []
        for document in corpus.documents:
            if document["technology"] != technology:
                continue
            pages = corpus.pages(document)
            for chunk in corpus.chunks(document):
                item = location(document, chunk)
                text = pages[item["document_index"]][item["start"]:item["end"]]
                if len(text) >= MIN_CHUNK_CHARACTERS and "```" not in text:
                    pool.append((order(digest(text)), item, text, has_ambiguous_use(text, aliases)))
        pool.sort(key=lambda entry: entry[0])
        picked, per_document = [], {}

        def take(entry):
            if per_document.get(entry[1]["source_key"], 0) >= MAX_CHUNKS_PER_DOCUMENT or entry in picked:
                return False
            per_document[entry[1]["source_key"]] = per_document.get(entry[1]["source_key"], 0) + 1
            picked.append(entry)
            return True

        for entry in pool:
            if entry[3] and take(entry):
                break
        else:
            fail(f"no chunk with an ambiguous name for {technology}")
        for entry in pool:
            if len(picked) == ENTITY_CHUNKS_PER_TECHNOLOGY:
                break
            take(entry)
        chosen += [{**item, "text": text, "ambiguous_stratum": ambiguous} for _, item, text, ambiguous in picked]
    for number, item in enumerate(chosen, 1):
        item["id"] = f"E{number:02d}"
    return chosen


def sample_keyterm_documents(corpus: Corpus) -> list[dict]:
    """Per technology, the document with the fewest chunks (at most 30); then the smallest in a format not yet
    covered. Ties go to seeded hash order."""
    counts = {d["source_key"]: len(corpus.chunks(d)) for d in corpus.documents}
    eligible = sorted((d for d in corpus.documents if counts[d["source_key"]] <= KEYTERM_MAX_CHUNKS),
                      key=lambda d: (counts[d["source_key"]], order(d["source_key"])))
    chosen = []
    for technology in sorted({d["technology"] for d in eligible}):
        chosen.append(next(d for d in eligible if d["technology"] == technology))
    formats = {d["format"] for d in chosen}
    rest = [d for d in eligible if d not in chosen]
    chosen.append(next((d for d in rest if d["format"] not in formats), rest[0]))
    return [{"id": f"K{number}", "source_key": d["source_key"], "technology": d["technology"], "format": d["format"],
             "chunks": counts[d["source_key"]], "document": d} for number, d in enumerate(chosen[:KEYTERM_DOCUMENTS], 1)]


HEADING = re.compile(r"\s*(?:#|[-*+]\s|\||>|```|\d+(?:\.\d+)*\.?(?:\s|$)|Chapter\s+\d)")


def prose_paragraphs(page: str):
    """Whole paragraphs of a page, so a passage never starts or ends inside a sentence. Skipped: headings, list items,
    tables, quotes, code, and short lines without punctuation (admonition labels such as Note, PDF running heads)."""
    for match in re.finditer(r"[^\n](?:.(?!\n[ \t]*\n))*.?", page, flags=re.S):
        block = match.group().rstrip()
        lines = block.splitlines()
        if any(HEADING.match(line) or line.startswith("    ")
               or (len(line.strip()) < 25 and not re.search(r"[.!?,;:]$", line.strip())) for line in lines):
            continue
        if MIN_PASSAGE_CHARACTERS <= len(block) <= MAX_PASSAGE_CHARACTERS and re.search(r"[.!?]$", block):
            yield match.start(), block


def draft(text: str) -> list[tuple[int, int]]:
    pieces, cursor = [], 0
    for match in NAIVE.finditer(text):
        pieces.append((cursor, match.start()))
        cursor = match.end()
    return pieces + [(cursor, len(text))]


def overlaps(item, spans) -> bool:
    return any(item["source_key"] == key and item["document_index"] == index and item["start"] < end and start < item["end"]
               for key, index, start, end in spans)


def sample_segmentation(corpus: Corpus, entity_spans: list) -> list[dict]:
    """Per technology, five whole prose paragraphs in seeded hash order, at most two per document, alternating between
    paragraphs with a hard case (abbreviation, dotted name, version, ellipsis, colon) and the rest, outside the
    entity chunks."""
    chosen = []
    for technology in sorted({d["technology"] for d in corpus.documents}):
        hard, plain = [], []
        for document in corpus.documents:
            if document["technology"] != technology:
                continue
            for index, page in enumerate(corpus.pages(document)):
                for start, block in prose_paragraphs(page):
                    item = {"source_key": document["source_key"], "technology": technology, "format": document["format"],
                            "document_index": index, "start": start, "end": start + len(block), "text": block, "draft": draft(block)}
                    if len(item["draft"]) >= 2 and not overlaps(item, entity_spans):
                        (hard if HARD.search(block) else plain).append((order(digest(block)), item))
        hard.sort(key=lambda entry: entry[0])
        plain.sort(key=lambda entry: entry[0])
        mixed = [entry for pair in zip(hard, plain) for entry in pair] + hard[len(plain):] + plain[len(hard):]
        # One per document first, then a second from each document in the same order, up to five per technology.
        picked = []
        for limit in (1, 2):
            for _, item in mixed:
                if len(picked) == PASSAGES_PER_TECHNOLOGY:
                    break
                if item not in picked and sum(p["source_key"] == item["source_key"] for p in picked) < limit:
                    picked.append(item)
        chosen += picked
    for number, item in enumerate(chosen, 1):
        item["id"] = f"S{number:02d}"
    return chosen


def marked(text: str, sentences) -> str:
    """The passage with a boundary mark after each sentence but the last."""
    out, cursor = [], 0
    for _, end in sentences[:-1]:
        out.append(text[cursor:end] + MARK)
        cursor = end
    return "".join(out) + text[cursor:]


def unmarked(text: str) -> tuple[str, list[list[int]]]:
    """Remove the marks; each sentence is the text between two marks without its surrounding whitespace."""
    pieces, cursor = [], 0
    for part in text.split(MARK):
        lead = len(part) - len(part.lstrip())
        pieces.append([cursor + lead, cursor + len(part.rstrip())])
        cursor += len(part)
    return text.replace(MARK, ""), pieces


def fence(text: str) -> str:
    return "~~~~text\n" + text + "\n~~~~"


def header(item, extra=""):
    return (f"## {item['id']}\n\n- Source: `{item['source_key']}` ({item['technology']}, {item['format']})\n"
            f"- Position: page {item['document_index']}, characters {item['start']} to {item['end']}{extra}\n")


def write_sheets(force: bool):
    if SHEETS.exists() and any(SHEETS.iterdir()) and not force:
        fail("data/nlp already has sheets; pass --force to overwrite them (filled labels would be lost)")
    corpus = Corpus()
    SHEETS.mkdir(parents=True, exist_ok=True)
    entities = sample_entities(corpus)
    lines = ["# Entity sheet (AC-07.4)", "", "Follow datasets/nlp/GUIDELINES.md. Under each chunk, write one mention per line in",
             "the `labels` block as `TYPE | exact text`. Leave the block empty if the chunk has no entity. Do not edit the text.", ""]
    for item in entities:
        lines += [header(item), fence(item["text"]), "", "~~~~labels", "~~~~", "", "Notes:", ""]
    (SHEETS / "entities_sheet.md").write_text("\n".join(lines), encoding="utf-8")
    keyterms = sample_keyterm_documents(corpus)
    lines = ["# Key-term sheet (AC-08.3)", "", "Follow datasets/nlp/GUIDELINES.md. Read each document's text file in data/nlp/keyterms/",
             "and list its key terms in the `terms` block, one per line, most important first.", ""]
    (SHEETS / "keyterms").mkdir(exist_ok=True)
    for item in keyterms:
        pages = corpus.pages(item["document"])
        name = f"{item['id']}.txt"
        (SHEETS / "keyterms" / name).write_text("\n\n".join(f"=== page {i} ===\n{page}" for i, page in enumerate(pages)), encoding="utf-8")
        lines += [f"## {item['id']}\n\n- Source: `{item['source_key']}` ({item['technology']}, {item['format']}, {item['chunks']} chunks)",
                  f"- Text: data/nlp/keyterms/{name}", "", "~~~~terms", "~~~~", ""]
    (SHEETS / "keyterms_sheet.md").write_text("\n".join(lines), encoding="utf-8")
    passages = sample_segmentation(corpus, [(i["source_key"], i["document_index"], i["start"], i["end"]) for i in entities])
    lines = ["# Segmentation sheet (AC-06.4)", "", f"Each `sentences` block is a whole paragraph with a {MARK} mark after every sentence",
             f"but the last. Add, move or delete marks to fix a boundary; never change any other character. Whitespace beside a",
             f"{MARK} belongs to neither sentence.", ""]
    for item in passages:
        lines += [header(item), "~~~~sentences", marked(item["text"], item["draft"]), "~~~~", ""]
    (SHEETS / "segmentation_sheet.md").write_text("\n".join(lines), encoding="utf-8")
    state = {"seed": SEED, "gazetteer_sha256": file_sha(GAZETTEER), "manifest_sha256": file_sha(MANIFEST),
             "entities": [{k: v for k, v in item.items() if k != "text"} | {"text_sha256": digest(item["text"])} for item in entities],
             "keyterms": [{k: v for k, v in item.items() if k != "document"} for item in keyterms],
             "segmentation": [{k: v for k, v in item.items() if k not in ("text", "draft")} | {"text_sha256": digest(item["text"])}
                              for item in passages]}
    (SHEETS / "sample.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    drafted = sum(len(item["draft"]) for item in passages)
    print(json.dumps({"result": "written", "entity_chunks": len(entities),
                      "ambiguous_stratum": sum(item["ambiguous_stratum"] for item in entities),
                      "keyterm_documents": [(i["id"], i["technology"], i["format"], i["chunks"]) for i in keyterms],
                      "passages": len(passages), "draft_sentences": drafted}, indent=1))


def blocks(path: Path, kind: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    found = {}
    # Only the sheet's own item headers: chunk text can hold Markdown headings of its own.
    for section in re.split(r"^## (?=[ESK]\d+\n)", text, flags=re.M)[1:]:
        identifier = section.split("\n", 1)[0].strip()
        match = re.search(rf"^~~~~{kind}\n(.*?)^~~~~$", section, flags=re.M | re.S)
        if match is None:
            fail(f"{path.name} {identifier} has no {kind} block")
        found[identifier] = match.group(1)
    return found


def freeze(reviewer: str, segmentation_only: bool):
    corpus = Corpus()
    state = json.loads((SHEETS / "sample.json").read_text(encoding="utf-8"))
    if state["manifest_sha256"] != file_sha(MANIFEST):
        fail("the manifest changed since the sheets were written")
    GOLD.mkdir(exist_ok=True)
    written = {}
    sentences = blocks(SHEETS / "segmentation_sheet.md", "sentences")
    rows = []
    for item in state["segmentation"]:
        text = corpus.span(item)
        plain, boundaries = unmarked(sentences[item["id"]][:-1])
        if plain != text:
            fail(f"{item['id']}: the marked passage differs from the passage; only marks may change")
        if any(start >= end for start, end in boundaries):
            fail(f"{item['id']}: an empty sentence between two marks")
        rows.append({k: item[k] for k in ("id", "source_key", "technology", "format", "document_index", "start", "end", "text_sha256")}
                    | {"anchor": text[:ANCHOR], "sentences": boundaries})
    written["segmentation"] = rows
    if not segmentation_only:
        if state["gazetteer_sha256"] != file_sha(GAZETTEER):
            fail("the gazetteer changed after sampling; resample or report the entity set as tuned (P9-9)")
        labels = blocks(SHEETS / "entities_sheet.md", "labels")
        rows = []
        for item in state["entities"]:
            text = corpus.span(item)
            mentions = set()
            for line in filter(str.strip, labels[item["id"]].splitlines()):
                kind, _, surface = (part.strip() for part in line.partition("|"))
                if kind not in TYPES or not surface:
                    fail(f"{item['id']}: bad label line {line!r}")
                if surface not in text:
                    fail(f"{item['id']}: {surface!r} is not in the chunk text exactly")
                mentions.add((normalized(surface), kind, surface))
            rows.append({k: item[k] for k in ("id", "source_key", "technology", "format", "document_index", "start", "end", "text_sha256",
                                              "ambiguous_stratum")}
                        | {"anchor": text[:ANCHOR], "mentions": [{"text": s, "normalized": n, "type": t} for n, t, s in sorted(mentions)]})
        written["entities"] = rows
        terms = blocks(SHEETS / "keyterms_sheet.md", "terms")
        rows = []
        for item in state["keyterms"]:
            listed = [normalized(term) for term in terms[item["id"]].splitlines() if term.strip()]
            if not listed or len(set(listed)) != len(listed):
                fail(f"{item['id']}: key terms missing or repeated")
            rows.append({k: item[k] for k in ("id", "source_key", "technology", "format", "chunks")} | {"terms": listed})
        written["keyphrases"] = rows
    hashes = {}
    for name, rows in written.items():
        path = GOLD / f"{name}_gold.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        hashes[path.name] = file_sha(path)
    entry = [f"\n## Frozen {date.today().isoformat()} by {reviewer}\n", f"- Seed `{SEED}`; manifest SHA-256 `{state['manifest_sha256']}`",
             f"- Gazetteer SHA-256 at sampling `{state['gazetteer_sha256']}`"]
    entry += [f"- `{name}` SHA-256 `{value}`" for name, value in hashes.items()]
    with (GOLD / "review_log.md").open("a", encoding="utf-8") as log:
        log.write("\n".join(entry) + "\n")
    print(json.dumps({"result": "frozen", "hashes": hashes,
                      "counts": {name: len(rows) for name, rows in written.items()},
                      "sentences": sum(len(row["sentences"]) for row in written["segmentation"])}, indent=1))


def check():
    corpus = Corpus()
    report = {}
    for name in ("segmentation", "entities", "keyphrases"):
        path = GOLD / f"{name}_gold.jsonl"
        if not path.exists():
            report[name] = "absent"
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if "text_sha256" in row:
                corpus.span(row)
            elif row["source_key"] not in corpus.by_key:
                fail(f"{row['id']}: {row['source_key']} left the evaluation scope")
        report[name] = {"rows": len(rows), "sha256": file_sha(path)}
    print(json.dumps({"result": "passed", "gazetteer_sha256": file_sha(GAZETTEER), **report}, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    sheets = commands.add_parser("sheets")
    sheets.add_argument("--force", action="store_true")
    frozen = commands.add_parser("freeze")
    frozen.add_argument("--reviewer", required=True)
    frozen.add_argument("--segmentation-only", action="store_true")
    commands.add_parser("check")
    args = parser.parse_args(argv)
    if args.command == "sheets":
        write_sheets(args.force)
    elif args.command == "freeze":
        freeze(args.reviewer, args.segmentation_only)
    else:
        check()


if __name__ == "__main__":
    sys.exit(main())
