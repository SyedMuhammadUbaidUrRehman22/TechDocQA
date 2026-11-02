"""Local persisted Chroma through LangChain; a derived view that registry eligibility always gates (FR-12)."""

from contextlib import contextmanager
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from techdocqa.errors import TechDocQAError

UPSERT_BATCH = 256
# Exact-recall search parameters; insertion stays single-threaded so a rebuild reproduces rankings.
HNSW = {"space": "cosine", "ef_construction": 200, "ef_search": 200, "max_neighbors": 32, "num_threads": 1}


class StoredVectors(Embeddings):
    """Hands Chroma already validated vectors, so the store itself never calls a model."""

    def __init__(self):
        self.pending = []

    def embed_documents(self, texts):
        vectors, self.pending = self.pending, []
        if len(vectors) != len(texts):
            raise ValueError("stored vectors do not match the documents")
        return vectors

    def embed_query(self, text):
        raise ValueError("queries are embedded by the configured provider")


@contextmanager
def store_errors():
    try:
        yield
    except TechDocQAError:
        raise
    except Exception:
        # Chroma raises several unrelated exception families, including from its native layer.
        raise TechDocQAError("VECTOR_STORE_FAILED", "The vector store operation failed safely.", stage="indexing", retryable=True) from None


class VectorStore:
    def __init__(self, data_directory, collection: str):
        import chromadb
        from langchain_chroma import Chroma
        path = str(Path(data_directory) / "index" / "chroma")
        self.vectors = StoredVectors()
        with store_errors():
            self.store = Chroma(collection_name=collection, embedding_function=self.vectors, persist_directory=path,
                client_settings=chromadb.config.Settings(anonymized_telemetry=False, is_persistent=True, persist_directory=path),
                collection_configuration={"hnsw": HNSW})

    def ids(self, **filters) -> set[str]:
        with store_errors():
            return set(self.store.get(include=[], **filters)["ids"])

    def empty(self) -> bool:
        with store_errors():
            return not self.store.get(include=[], limit=1)["ids"]

    def upsert(self, entries: list[tuple[str, str, dict, list[float]]]) -> None:
        """Entries are (id, text, scalar metadata, vector); repeating an ID replaces it."""
        with store_errors():
            for start in range(0, len(entries), UPSERT_BATCH):
                batch = entries[start:start + UPSERT_BATCH]
                self.vectors.pending = [entry[3] for entry in batch]
                self.store.add_documents([Document(page_content=entry[1], metadata=entry[2]) for entry in batch],
                                         ids=[entry[0] for entry in batch])

    def delete(self, ids) -> int:
        ids = list(ids)
        with store_errors():
            for start in range(0, len(ids), UPSERT_BATCH):
                self.store.delete(ids=ids[start:start + UPSERT_BATCH])
        return len(ids)

    def reset(self) -> None:
        with store_errors():
            self.store.reset_collection()

    def search(self, vector: list[float], k: int, where: dict) -> list[tuple[Document, float]]:
        """Nearest documents with a 0-1 relevance: (cosine + 1) / 2, which equals 1 - distance / 2."""
        with store_errors():
            found = self.store.similarity_search_by_vector_with_relevance_scores(vector, k=k, filter=where)
        return [(document, max(0.0, min(1.0, 1 - distance / 2))) for document, distance in found]
