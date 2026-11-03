"""Citation labels from model output, verified against the supplied chunks and resolved from stored metadata only (FR-17).

A valid label proves which supplied chunk the model pointed at, not that the chunk supports the claim;
human review checks support separately (AC-16.6).
"""

import re

from techdocqa.ingestion.chunks import stored_chunks
from techdocqa.schemas import Citation, SourceReference

# [C1], [C1, C2] or [C1; C2]. The leading spaces belong to the marker so a removed one leaves no gap.
MARKER = re.compile(r"([ \t]*)\[\s*(C\d{1,3}(?:\s*[,;]\s*C\d{1,3})*)\s*\]")
SEPARATOR = re.compile(r"\s*[,;]\s*")


def cited_labels(answer: str) -> list[str]:
    """Labels in order of first appearance, each once."""
    found = []
    for match in MARKER.finditer(answer):
        for label in SEPARATOR.split(match.group(2)):
            if label not in found:
                found.append(label)
    return found


def remove_labels(answer: str, labels: set[str]) -> str:
    """Drops the given labels from their markers; a marker left empty disappears with its leading space."""
    if not labels:
        return answer
    def keep(match):
        cited = SEPARATOR.split(match.group(2))
        if not labels.intersection(cited):
            return match.group(0)
        remaining = [label for label in cited if label not in labels]
        return match.group(1) + "[" + ", ".join(remaining) + "]" if remaining else ""
    return MARKER.sub(keep, answer).strip()


def resolve_citations(labels: list[str], supplied: dict, settings, registry) -> tuple[list[Citation], list[str]]:
    """Citation objects for labels of supplied results whose chunk is still active now, after generation.

    Returns the citations and the labels whose version was withdrawn, superseded or re-chunked meanwhile.
    Titles and sources come from the registry and sections and pages from the stored chunk, never from the model.
    """
    eligible = {record.version_id: record for record in registry.eligible_versions()}
    chunks, citations, inactive = {}, [], []
    for label in labels:
        result = supplied[label]
        record = eligible.get(result.version_id)
        if record is not None and record.version_id not in chunks:
            chunks[record.version_id] = {chunk["chunk_id"]: chunk for chunk in stored_chunks(record, settings)}
        chunk = chunks[record.version_id].get(result.chunk_id) if record is not None else None
        if chunk is None:
            inactive.append(label)
            continue
        citations.append(Citation(label=label, chunk_id=chunk["chunk_id"], document_id=record.document_id,
            version_id=record.version_id, title=record.title, section_path=" > ".join(chunk["section_path"]) or None,
            source=record.source_key, source_url=record.source_url, page=chunk["page"]))
    return citations, inactive


def unique_sources(citations: list[Citation]) -> list[SourceReference]:
    seen, sources = set(), []
    for citation in citations:
        if citation.version_id not in seen:
            seen.add(citation.version_id)
            sources.append(SourceReference(document_id=citation.document_id, version_id=citation.version_id,
                                           title=citation.title, source=citation.source, source_url=citation.source_url))
    return sources
