from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class VectorSearchResult:
    vector_id: int
    score: float


class FaissVectorStore:
    def __init__(self, index_path: Path | None = None):
        self.index_path = index_path or Path("data/vector_index/reference_chunks.faiss")
        self.vectors_path = self.index_path.with_suffix(".npy")
        self.ids_path = self.index_path.with_suffix(".ids.npy")

    def save(self, vectors: np.ndarray, vector_ids: list[int]) -> None:
        faiss = _faiss()
        if len(vectors) != len(vector_ids):
            raise ValueError("vectors와 vector_ids 길이가 다릅니다.")
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        dimension = vectors.shape[1]
        index = faiss.IndexIDMap(faiss.IndexFlatIP(dimension))
        index.add_with_ids(vectors.astype("float32"), np.asarray(vector_ids, dtype="int64"))
        faiss.write_index(index, str(self.index_path))
        np.save(self.vectors_path, vectors.astype("float32"))
        np.save(self.ids_path, np.asarray(vector_ids, dtype="int64"))

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[VectorSearchResult]:
        if not self.vectors_path.exists() or not self.ids_path.exists():
            return []
        vectors = np.load(self.vectors_path)
        vector_ids = np.load(self.ids_path)
        if vectors.size == 0:
            return []
        query = np.asarray(query_vector, dtype="float32")
        scores = vectors @ query
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [VectorSearchResult(vector_id=int(vector_ids[index]), score=float(scores[index])) for index in top_indices]


def _faiss():
    try:
        import faiss
    except Exception as exc:
        raise RuntimeError("faiss-cpu가 설치되어 있지 않습니다.") from exc
    return faiss


reference_vector_store = FaissVectorStore()
