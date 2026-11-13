"""Framework BM25 over eligible chunks, with identifiers kept searchable (FR-13)."""

import math
import re

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

TOKENIZER_POLICY = "technical-tokens-v1"
# Relevance is the raw score over the most this query could score; see LexicalIndex.ceiling.
RELEVANCE_POLICY = "bm25-query-max-v1"
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

    def ceiling(self, tokens: list[str]) -> float:
        """The most any chunk could score for these tokens: each adds at most IDF x (k1 + 1) as its frequency grows.

        A token the corpus lacks scores nothing but counts at the IDF of an unseen term, so a question about words
        the documents never use cannot look relevant on its few common words.
        """
        vectorizer = self.vectorizer
        unseen = math.log(vectorizer.corpus_size + 0.5) - math.log(0.5)
        return (vectorizer.k1 + 1) * sum(vectorizer.idf.get(token, unseen) for token in tokens)

    def search(self, query: str, top_k: int, allowed=lambda chunk: True) -> list[tuple[dict, float, float]]:
        """(chunk, raw score, 0-1 relevance). Scores every chunk before filtering, so a rare filter cannot starve results."""
        tokens = tokenize(query)
        wanted = set(tokens)
        if not wanted:
            return []
        scores = self.vectorizer.get_scores(tokens)
        # IDF can reach zero in a small corpus, so a match is a shared token rather than a positive score.
        matches = [(chunk, float(score)) for chunk, score, frequencies
                   in zip(self.chunks, scores, self.vectorizer.doc_freqs, strict=True)
                   if wanted.intersection(frequencies) and allowed(chunk)]
        matches.sort(key=lambda item: (-item[1], item[0]['chunk_id']))
        # Dividing by a per-query constant keeps the ranking. A tiny corpus can give negative IDFs, hence the clamp.
        ceiling = self.ceiling(tokens)
        return [(chunk, score, min(1.0, max(0.0, score / ceiling)) if ceiling > 0 else 0.0) for chunk, score in matches[:top_k]]

    def scored(self, query: str, chunk_ids: set[str]) -> dict[str, tuple[float, float]]:
        """(raw score, 0-1 relevance) for the named chunks, on the same scale as search(); a chunk sharing no query
        token scores 0. Hybrid uses it for chunks that only the vector retriever ranked (P10-3)."""
        tokens = tokenize(query)
        if not tokens:
            return {chunk['chunk_id']: (0.0, 0.0) for chunk in self.chunks if chunk['chunk_id'] in chunk_ids}
        wanted, ceiling = set(tokens), self.ceiling(tokens)
        scores = self.vectorizer.get_scores(tokens)
        found = {}
        for chunk, score, frequencies in zip(self.chunks, scores, self.vectorizer.doc_freqs, strict=True):
            if chunk['chunk_id'] in chunk_ids:
                score = float(score) if wanted.intersection(frequencies) else 0.0
                found[chunk['chunk_id']] = score, (min(1.0, max(0.0, score / ceiling)) if ceiling > 0 else 0.0)
        return found
