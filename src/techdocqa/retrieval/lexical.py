"""Framework BM25 over eligible chunks, with identifiers kept searchable (FR-13)."""

import re

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

TOKENIZER_POLICY = "technical-tokens-v1"
# Whole technical forms: --flags, snake_case, dotted.names, HTTP/2, C++, C#.
TECHNICAL = re.compile(r"-{1,2}[^\W\d_][\w-]*|\w+(?:[./:#+-]+\w+)*(?:\+\+|#)?")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
WORD = re.compile(r"[^\W_]+")


def tokenize(text: str) -> list[str]:
    """Case-folded whole technical tokens, each followed by its plain word-level parts."""
    tokens = []
    for match in TECHNICAL.finditer(text):
        whole = match.group().casefold()
        tokens.append(whole)
        for word in WORD.findall(match.group()):
            parts = CAMEL.sub(" ", word).split()
            views = [word, *parts] if len(parts) > 1 else [word]
            tokens.extend(view.casefold() for view in views if view.casefold() != whole)
    return tokens


class LexicalIndex:
    """Corpus statistics stay those of all eligible chunks, so a filter never changes a chunk's score."""

    def __init__(self, chunks: list[dict], k1: float, b: float):
        self.chunks = chunks
        documents = [Document(page_content=chunk['text']) for chunk in chunks]
        self.vectorizer = BM25Retriever.from_documents(documents, preprocess_func=tokenize,
                                                       bm25_params={'k1': k1, 'b': b}).vectorizer

    def search(self, query: str, top_k: int, allowed=lambda chunk: True) -> list[tuple[dict, float]]:
        """Scores every chunk before filtering, so a rare filter cannot starve results."""
        wanted = set(tokenize(query))
        if not wanted:
            return []
        scores = self.vectorizer.get_scores(tokenize(query))
        # IDF can reach zero in a small corpus, so a match is a shared token rather than a positive score.
        matches = [(chunk, float(score)) for chunk, score, frequencies
                   in zip(self.chunks, scores, self.vectorizer.doc_freqs, strict=True)
                   if wanted.intersection(frequencies) and allowed(chunk)]
        matches.sort(key=lambda item: (-item[1], item[0]['chunk_id']))
        return matches[:top_k]
