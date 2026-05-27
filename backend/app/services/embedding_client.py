from __future__ import annotations

import numpy as np
import requests

from app.core.config import get_settings


class EmbeddingClient:
    def embed(self, text: str) -> np.ndarray:
        data = self._post("/embed", {"text": text})
        return np.asarray(data["embedding"], dtype="float32")

    def embed_many(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype="float32")
        data = self._post("/embed-many", {"texts": texts})
        return np.asarray(data["embeddings"], dtype="float32")

    def _post(self, path: str, payload: dict) -> dict:
        settings = get_settings()
        url = settings.embedding_server_url.rstrip("/") + path
        try:
            response = requests.post(url, json=payload, timeout=settings.embedding_request_timeout_seconds)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"임베딩 서버에 연결할 수 없습니다. {settings.embedding_server_url} 서버가 실행 중인지 확인해주세요."
            ) from exc


embedding_client = EmbeddingClient()
