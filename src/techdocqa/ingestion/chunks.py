"""Bounded offline chunk generation and atomic registry activation."""

import hashlib
import json
from pathlib import Path
import tempfile

from techdocqa.chunking import effective_config
from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.online import store_snapshot
from techdocqa.ingestion.processing import finalized_documents, read_snapshot, run_processing_worker
from techdocqa.schemas import BatchResult, ChunkingProvenance


class ChunkingBatchResult(BatchResult):
    chunk_count: int


def verify_chunking(record, settings, registry, info=None) -> dict:
    info = info or record.chunking
    if info is None:
        raise TechDocQAError("INVALID_STATE", "This version has no chunks.", stage="chunking")
    try:
        raw = read_snapshot(Path(settings.data_directory), info.snapshot_path, info.snapshot_hash,
                            settings.ingestion.max_file_bytes * 8)
        data = json.loads(raw)
        config_id = hashlib.sha256(json.dumps(data['config'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if config_id != info.chunking_config_id or data['chunking_config_id'] != config_id or data['config'] != info.config:
            raise ValueError
        documents = finalized_documents(record.version_id, settings, registry)
        if len(data['sentence_spans']) != len(documents) or len(data['chunks']) != info.chunk_count:
            raise ValueError
        sentence_count = 0
        for index, page in enumerate(data['sentence_spans']):
            document = documents[index]
            if page['document_index'] != index or page['page'] != document.metadata.get('page'):
                raise ValueError
            cursor = 0
            for span in page['spans']:
                if (type(span['start']) is not int or type(span['end']) is not int
                        or span['start'] != cursor or not cursor < span['end'] <= len(document.page_content)):
                    raise ValueError
                cursor = span['end']
            if cursor != len(document.page_content):
                raise ValueError
            sentence_count += len(page['spans'])
        if sentence_count != info.sentence_count:
            raise ValueError
        seen = set()
        coverage = [0] * len(documents)
        for index, chunk in enumerate(data['chunks']):
            if type(chunk['document_index']) is not int or not 0 <= chunk['document_index'] < len(documents):
                raise ValueError
            document = documents[chunk['document_index']]
            start, end = chunk['start'], chunk['end']
            section_path = []
            for heading in document.metadata.get('headings', []):
                if heading['start'] <= start:
                    section_path = heading['section_path']
                else:
                    break
            identity = [record.version_id, config_id, chunk['document_index'], start, end]
            chunk_id = 'chk_' + hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()
            if (not 0 <= start < end <= len(document.page_content) or chunk['chunk_index'] != index
                    or chunk['chunk_id'] != chunk_id or chunk_id in seen
                    or chunk['document_id'] != record.document_id or chunk['version_id'] != record.version_id
                    or chunk['chunking_config_id'] != config_id or chunk['page'] != document.metadata.get('page')
                    or chunk['section_path'] != section_path
                    or chunk['text'] != document.page_content[start:end] or not chunk['text'].strip()
                    or chunk['size'] != len(chunk['text']) or chunk['size'] > data['config']['size']
                    or chunk['text_hash'] != hashlib.sha256(chunk['text'].encode()).hexdigest()):
                raise ValueError
            profile = data['config'].get('embedding_input')
            if profile and (len(chunk['text'].encode('utf-8')) + len(profile['prefix'].encode('utf-8'))
                            + profile['special_tokens_reserved'] > profile['context_tokens']):
                raise ValueError
            covered = coverage[chunk['document_index']]
            if start > covered and document.page_content[covered:start].strip():
                raise ValueError
            coverage[chunk['document_index']] = max(covered, end)
            seen.add(chunk_id)
        if any(doc.page_content[end:].strip() for doc, end in zip(documents, coverage, strict=True)):
            raise ValueError
        return data
    except (ValueError, KeyError, TypeError, IndexError):
        raise TechDocQAError("SNAPSHOT_MISMATCH", "Chunk artifact failed verification.", stage="storage") from None


def active_chunks(version_id, settings, registry) -> list[dict]:
    record = registry.get_version(version_id)
    if not record.finalized or not record.is_active or record.duplicate_of:
        return []
    return verify_chunking(record, settings, registry)['chunks'] if record.chunking else []


def chunk_versions(version_ids, settings, registry) -> ChunkingBatchResult:
    root = Path(settings.data_directory).resolve()
    config_id, config = effective_config(settings.chunking, settings.model)
    with registry.registration_lock():
        registry.recover_interrupted_runs()
        if not version_ids:
            version_ids = [row[0] for row in registry.execute(
                "SELECT version_id FROM registrations WHERE finalized=1 AND is_active=1 AND duplicate_of IS NULL ORDER BY document_id"
            ).fetchall()]
        if not version_ids:
            raise TechDocQAError("INVALID_ARGUMENT", "No eligible versions are available.", stage="chunking")
        run_id, attempts = registry.start_run(len(version_ids), stage='chunking')
        counts = {}
        for version_id, attempt_id in zip(version_ids, attempts, strict=True):
            try:
                registry.begin_chunking(version_id, attempt_id)
                record = registry.get_version(version_id)
                skipped = bool(record.chunking and record.chunking.chunking_config_id == config_id)
                if skipped:
                    verify_chunking(record, settings, registry)
                    info = record.chunking
                else:
                    documents = finalized_documents(version_id, settings, registry)
                    with tempfile.TemporaryDirectory(prefix='chunking-', dir=root) as working:
                        directory = Path(working)
                        (directory / 'input.json').write_text(json.dumps([
                            {'page_content': doc.page_content, 'metadata': doc.metadata} for doc in documents
                        ], ensure_ascii=True), encoding='utf-8')
                        run_processing_worker({'directory': working, 'chunking': settings.chunking.model_dump(),
                                               'model': settings.model.model_dump()}, settings)
                        limit = settings.ingestion.max_file_bytes * 8
                        with (directory / 'chunks.json').open('rb') as handle:
                            raw = handle.read(limit + 1)
                        if len(raw) > limit:
                            raise TechDocQAError("TEXT_TOO_LARGE", "Chunk artifact exceeds the bounded storage limit.", stage='chunking')
                        data = json.loads(raw)
                        snapshot, digest = store_snapshot(root, 'artifacts', raw, '.json', namespace='chunking')
                    info = ChunkingProvenance(snapshot_path=snapshot.relative_to(root).as_posix(), snapshot_hash=digest,
                        chunking_config_id=config_id, chunk_count=len(data['chunks']),
                        sentence_count=sum(len(page['spans']) for page in data['sentence_spans']), config=config)
                    verify_chunking(record, settings, registry, info)
                registry.save_chunking(version_id, info, attempt_id, skipped=skipped)
                counts[version_id] = info.chunk_count
            except TechDocQAError as error:
                registry.fail_attempt(attempt_id, error.response.error)
            except (OSError, ValueError, TypeError, KeyError):
                registry.fail_attempt(attempt_id, TechDocQAError("CHUNKING_FAILED", "Chunking failed safely.", stage='chunking').response.error)
        registry.finish_run(run_id)
        return ChunkingBatchResult(**registry.get_run(run_id).model_dump(), chunk_count=sum(counts.values()))
