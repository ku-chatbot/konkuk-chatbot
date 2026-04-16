from __future__ import annotations

from functools import cached_property

import numpy as np

from app.core.config import get_settings


class LocalEmbeddingService:
    @cached_property
    def model(self):
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        return SentenceTransformer(settings.local_embedding_model, device="cpu")

    def embed(self, text: str) -> np.ndarray:
        vector = self.model.encode(text, normalize_embeddings=True)
        return np.asarray(vector, dtype="float32")

    def embed_many(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for index, text in enumerate(texts):
            if index % 10 == 0:
                print(f"[embedding] chunk {index + 1}/{len(texts)}", flush=True)
            vector = self.model.encode(text, normalize_embeddings=True, batch_size=1, show_progress_bar=False)
            vectors.append(np.asarray(vector, dtype="float32"))
        return np.vstack(vectors).astype("float32")


local_embedding_service = LocalEmbeddingService()
