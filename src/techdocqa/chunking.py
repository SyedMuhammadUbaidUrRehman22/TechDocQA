"""Framework character splitting with code and provenance boundaries (FR-10)."""

import hashlib
from importlib.metadata import version
import json
from math import ceil
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from techdocqa.errors import TechDocQAError
from techdocqa.normalization import code_spans
from techdocqa.segmentation import POLICIES, segmenter, spacy_version
from techdocqa.settings import ChunkingSettings, ModelSettings

CHUNKING_POLICY = "source-preserving-chunks-v3"
WHITESPACE = re.compile(r"\s+")


def verified_embedding_profile(model: ModelSettings) -> bool:
    # shortcut: only these tokenizers are known to emit at most one token per UTF-8 byte; add others after verifying that.
    if not model.embedding_context_window:
        return False
    if model.provider == 'ollama':
        return (model.embedding_model.split(':')[0] == 'nomic-embed-text' and model.embedding_tokenizer == 'bert'
                and bool(model.embedding_model_digest))
    return model.embedding_tokenizer == 'tiktoken'


def effective_config(settings: ChunkingSettings, model: ModelSettings | None = None) -> tuple[str, dict]:
    model = model or ModelSettings()
    # The segmentation setting enters as its policy ID. The P0 default keeps the exact values, and so the configuration
    # ID, that every existing chunk artifact was made with; the spaCy policy also records the library version.
    values = {**settings.model_dump(exclude={"segmentation"}), "policy": CHUNKING_POLICY,
              "segmentation_policy": POLICIES[settings.segmentation], "effective_unit": "characters",
              "tokenizer": "python.len", "tokenizer_version": "unicode-codepoints-v1",
              "fallback_reason": "provider_tokenizer_unavailable" if settings.unit == "tokens" else None,
              "splitter": "RecursiveCharacterTextSplitter",
              "splitter_version": version("langchain-text-splitters")}
    if settings.segmentation != "rules":
        if spacy_version() is None:
            raise TechDocQAError("SEGMENTER_UNAVAILABLE", "The spaCy segmentation policy needs the nlp extra.", stage="configuration")
        values["segmentation_library"] = {"spacy": spacy_version()}
    values['embedding_input'] = None
    if model.embedding_model:
        if not verified_embedding_profile(model):
            raise TechDocQAError('EMBEDDING_PROFILE_UNVERIFIED',
                'Verify the installed embedding context, tokenizer and model digest before chunking.', stage='configuration')
        # Tokens never outnumber UTF-8 bytes for these tokenizers; reserve CLS/SEP and the task prefix.
        overhead = len(model.embedding_prefix.encode('utf-8')) + 2
        byte_limit = model.embedding_context_window - overhead
        if byte_limit <= settings.overlap or byte_limit < settings.minimum:
            raise TechDocQAError('INVALID_CONFIGURATION',
                'Embedding input bound cannot fit the configured minimum and overlap.', stage='configuration')
        values['embedding_input'] = {'provider': model.provider, 'model': model.embedding_model,
            'model_digest': model.embedding_model_digest, 'context_tokens': model.embedding_context_window,
            'tokenizer_family': model.embedding_tokenizer, 'counting': 'utf8-byte-upper-bound-v1',
            'prefix': model.embedding_prefix, 'special_tokens_reserved': 2, 'byte_limit': byte_limit,
            'validation': 'conservative_bound_not_exact_token_count'}
    serialized = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest(), values


def size_measure(size: int, byte_limit: int | None):
    """Length on the configured size scale: characters, raised when bytes near the embedding bound."""
    if byte_limit is None:
        return len
    return lambda value: max(len(value), ceil(len(value.encode('utf-8')) * size / byte_limit))


def split_ranges(text: str, start: int, end: int, size: int, measure=len, *, code: bool = False) -> list[dict]:
    # Literal ". " can also follow an abbreviation; that only moves a soft boundary, never coverage.
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=0,
        separators=["\n", ""] if code else ["\n\n", "\n", ". ", "? ", "! ", " ", ""],
        keep_separator="end", strip_whitespace=False, length_function=measure)
    value = text[start:end]
    parts = splitter.split_text(value)
    if ''.join(parts) != value:
        raise TechDocQAError("CHUNK_COVERAGE_FAILED", "Framework splitting changed source coverage.", stage="chunking")
    ranges = []
    for part in parts:
        ranges.append({"start": start, "end": start + len(part), "oversize_split": code})
        start += len(part)
    return ranges


def word_start(text: str, start: int, limit: int) -> int:
    """First word boundary at or after start, so overlap never begins mid-word."""
    if text[start - 1:start].isspace():
        return start
    match = WHITESPACE.search(text, start, limit)
    return match.end() if match else limit


def section_ranges(text: str, metadata: dict, blocks: list[dict]) -> list[tuple]:
    headings = metadata.get("headings", [])
    if any(type(h.get("start")) is not int or not 0 <= h["start"] < len(text)
           or not isinstance(h.get("section_path"), list) for h in headings):
        raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "Heading boundaries are invalid.", stage="chunking")
    if any(a["start"] >= b["start"] for a, b in zip(headings, headings[1:])):
        raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "Heading boundaries are unordered.", stage="chunking")
    if any(block["start"] < h["start"] < block["end"] for block in blocks for h in headings):
        raise TechDocQAError("INVALID_EXTRACTED_CONTENT", "A heading splits protected code.", stage="chunking")
    boundaries = [(0, [])]
    for heading in headings:
        if heading["start"] == 0:
            boundaries[0] = (0, heading["section_path"])
        else:
            boundaries.append((heading["start"], heading["section_path"]))
    return [(start, boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text), path)
            for i, (start, path) in enumerate(boundaries)]


def build_chunks(documents, settings: ChunkingSettings, *, model: ModelSettings | None = None) -> dict:
    config_id, config = effective_config(settings, model)
    profile = config['embedding_input']
    measure = size_measure(settings.size, profile['byte_limit'] if profile else None)
    sentence_spans = segmenter(settings.segmentation)
    chunks, spans = [], []
    target = settings.size - settings.overlap
    for document_index, document in enumerate(documents):
        text, metadata = document.page_content, document.metadata
        cost = lambda begin, stop: measure(text[begin:stop])
        protected = code_spans(text, metadata.get("code_spans"))
        blocks = [span for span in protected if span["kind"] == "block"]
        spans.append({"document_index": document_index, "page": metadata.get("page"),
                      "spans": sentence_spans(text, protected)})
        for begin, end, section_path in section_ranges(text, metadata, blocks):
            atoms, cursor = [], begin
            for block in blocks:
                if not begin <= block["start"] < end:
                    continue
                if cursor < block["start"]:
                    atoms.extend(split_ranges(text, cursor, block["start"], target, measure))
                if cost(block["start"], block["end"]) <= settings.size:
                    atoms.append({"start": block["start"], "end": block["end"], "oversize_split": False})
                else:
                    atoms.extend(split_ranges(text, block["start"], block["end"], settings.size, measure, code=True))
                cursor = block["end"]
            if cursor < end:
                atoms.extend(split_ranges(text, cursor, end, target, measure))
            merged = []
            for atom in atoms:
                if merged and cost(merged[-1]["start"], atom["end"]) <= target:
                    merged[-1]["end"] = atom["end"]
                    merged[-1]["oversize_split"] |= atom["oversize_split"]
                else:
                    merged.append(dict(atom))
            index = 0
            while index < len(merged):
                item = merged[index]
                if item['end'] - item['start'] < settings.minimum:
                    if index and cost(merged[index - 1]['start'], item['end']) <= settings.size:
                        merged[index - 1]['end'] = item['end']
                        merged[index - 1]['oversize_split'] |= item['oversize_split']
                        merged.pop(index)
                        continue
                    if index + 1 < len(merged) and cost(item['start'], merged[index + 1]['end']) <= settings.size:
                        merged[index + 1]['start'] = item['start']
                        merged[index + 1]['oversize_split'] |= item['oversize_split']
                        merged.pop(index)
                        continue
                index += 1
            previous_end = begin
            for item in merged:
                base_start, stop = item['start'], item['end']
                start = max(begin, base_start - min(settings.overlap, settings.size - (stop - base_start)))
                while start < base_start and cost(start, stop) > settings.size:
                    start += 1
                if begin < start < base_start:
                    start = word_start(text, start, base_start)
                for block in blocks:
                    if block['start'] < start < block['end']:
                        if cost(block['start'], block['end']) <= settings.size:
                            start = min(base_start, block['end'])
                        elif text[start - 1:start] != '\n':
                            next_line = text.find('\n', start, base_start)
                            start = next_line + 1 if next_line >= 0 else base_start
                value = text[start:stop]
                if not value.strip():
                    continue
                identity = [metadata['version_id'], config_id, document_index, start, stop]
                chunk = {key: metadata.get(key) for key in ('document_id', 'version_id', 'title', 'technology',
                    'category', 'source_url', 'license', 'version_label', 'language')}
                chunk.update(chunk_id='chk_' + hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest(),
                    chunk_index=len(chunks), document_index=document_index, section_path=section_path,
                    page=metadata.get('page'), start=start, end=stop, text=value, size=len(value),
                    size_unit='characters', chunking_config_id=config_id,
                    text_hash=hashlib.sha256(value.encode('utf-8')).hexdigest(),
                    oversize_split=item['oversize_split'], overlap_characters=max(0, previous_end - start),
                    minimum_exception='provenance_or_size_boundary' if len(value) < settings.minimum else None,
                    overlap_exception='code_or_size_boundary' if settings.overlap and base_start > begin and start == base_start else None)
                chunks.append(chunk)
                previous_end = stop
    if not chunks:
        raise TechDocQAError("NO_CHUNKS", "No usable chunks were produced.", stage="chunking")
    if profile:
        overhead = len(profile['prefix'].encode('utf-8')) + profile['special_tokens_reserved']
        if any(len(chunk['text'].encode('utf-8')) + overhead > profile['context_tokens'] for chunk in chunks):
            raise TechDocQAError('EMBEDDING_INPUT_LIMIT', 'A chunk exceeds the embedding input bound.', stage='chunking')
    return {"chunking_config_id": config_id, "config": config, "sentence_spans": spans, "chunks": chunks}
