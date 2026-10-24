"""Framework character splitting with code and provenance boundaries (FR-10)."""

import hashlib
from importlib.metadata import version
import json

from langchain_text_splitters import RecursiveCharacterTextSplitter

from techdocqa.errors import TechDocQAError
from techdocqa.normalization import code_spans
from techdocqa.segmentation import SEGMENTATION_POLICY, sentence_spans
from techdocqa.settings import ChunkingSettings, ModelSettings

CHUNKING_POLICY = "source-preserving-chunks-v2"


def effective_config(settings: ChunkingSettings, model: ModelSettings | None = None) -> tuple[str, dict]:
    model = model or ModelSettings()
    values = {**settings.model_dump(), "policy": CHUNKING_POLICY,
              "segmentation_policy": SEGMENTATION_POLICY, "effective_unit": "characters",
              "tokenizer": "python.len", "tokenizer_version": "unicode-codepoints-v1",
              "fallback_reason": "provider_tokenizer_unavailable" if settings.unit == "tokens" else None,
              "splitter": "RecursiveCharacterTextSplitter",
              "splitter_version": version("langchain-text-splitters")}
    values['embedding_input'] = None
    if model.embedding_model:
        # shortcut: only nomic's verified BERT profile is supported; add a provider tokenizer for other models.
        if (model.provider != 'ollama' or model.embedding_model.split(':')[0] != 'nomic-embed-text'
                or model.embedding_tokenizer != 'bert' or not model.embedding_context_window
                or not model.embedding_model_digest):
            raise TechDocQAError('EMBEDDING_PROFILE_UNVERIFIED',
                'Verify the installed embedding context, tokenizer and model digest before chunking.', stage='configuration')
        # WordPiece emits at most one token per input UTF-8 byte; reserve CLS/SEP and the task prefix.
        overhead = len(model.embedding_prefix.encode('utf-8')) + 2
        cap = (model.embedding_context_window - overhead) // 4
        values['requested_size'] = settings.size
        values['size'] = min(settings.size, cap)
        if values['size'] <= settings.overlap or values['size'] < settings.minimum:
            raise TechDocQAError('INVALID_CONFIGURATION',
                'Embedding input bound cannot fit the configured minimum and overlap.', stage='configuration')
        values['embedding_input'] = {'provider': model.provider, 'model': model.embedding_model,
            'model_digest': model.embedding_model_digest, 'context_tokens': model.embedding_context_window,
            'tokenizer_family': model.embedding_tokenizer, 'counting': 'utf8-byte-upper-bound-v1',
            'prefix': model.embedding_prefix, 'special_tokens_reserved': 2,
            'validation': 'conservative_bound_not_exact_token_count'}
    serialized = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest(), values


def split_ranges(text: str, start: int, end: int, size: int, *, code: bool = False) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=0,
        separators=["\n", ""] if code else ["\n\n", "\n", " ", ""],
        keep_separator="end", strip_whitespace=False)
    value = text[start:end]
    parts = splitter.split_text(value)
    if ''.join(parts) != value:
        raise TechDocQAError("CHUNK_COVERAGE_FAILED", "Framework splitting changed source coverage.", stage="chunking")
    ranges = []
    for part in parts:
        ranges.append({"start": start, "end": start + len(part), "oversize_split": code})
        start += len(part)
    return ranges


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
    settings = settings.model_copy(update={'size': config['size']})
    chunks, spans = [], []
    target = settings.size - settings.overlap
    for document_index, document in enumerate(documents):
        text, metadata = document.page_content, document.metadata
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
                    atoms.extend(split_ranges(text, cursor, block["start"], target))
                if block["end"] - block["start"] <= settings.size:
                    atoms.append({"start": block["start"], "end": block["end"], "oversize_split": False})
                else:
                    atoms.extend(split_ranges(text, block["start"], block["end"], settings.size, code=True))
                cursor = block["end"]
            if cursor < end:
                atoms.extend(split_ranges(text, cursor, end, target))
            merged = []
            for atom in atoms:
                if merged and atom["end"] - merged[-1]["start"] <= target:
                    merged[-1]["end"] = atom["end"]
                    merged[-1]["oversize_split"] |= atom["oversize_split"]
                else:
                    merged.append(dict(atom))
            index = 0
            while index < len(merged):
                item = merged[index]
                if item['end'] - item['start'] < settings.minimum:
                    if index and item['end'] - merged[index - 1]['start'] <= settings.size:
                        merged[index - 1]['end'] = item['end']
                        merged[index - 1]['oversize_split'] |= item['oversize_split']
                        merged.pop(index)
                        continue
                    if index + 1 < len(merged) and merged[index + 1]['end'] - item['start'] <= settings.size:
                        merged[index + 1]['start'] = item['start']
                        merged[index + 1]['oversize_split'] |= item['oversize_split']
                        merged.pop(index)
                        continue
                index += 1
            previous_end = begin
            for item in merged:
                base_start, stop = item['start'], item['end']
                start = max(begin, base_start - min(settings.overlap, settings.size - (stop - base_start)))
                for block in blocks:
                    if block['start'] < start < block['end']:
                        if block['end'] - block['start'] <= settings.size:
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
    if config['embedding_input']:
        profile = config['embedding_input']
        overhead = len(profile['prefix'].encode('utf-8')) + profile['special_tokens_reserved']
        if any(len(chunk['text'].encode('utf-8')) + overhead > profile['context_tokens'] for chunk in chunks):
            raise TechDocQAError('EMBEDDING_INPUT_LIMIT', 'A chunk exceeds the embedding input bound.', stage='chunking')
    return {"chunking_config_id": config_id, "config": config, "sentence_spans": spans, "chunks": chunks}
