from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import FastAPI

from app.core.config import get_settings
from app.services.local_embedding import local_embedding_service


app = FastAPI(title="KU-Bot Embedding Server")


class EmbedRequest(BaseModel):
    text: str = Field(min_length=1)


class EmbedManyRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": get_settings().local_embedding_model}


@app.post("/embed")
def embed(payload: EmbedRequest) -> dict[str, list[float]]:
    vector = local_embedding_service.embed(payload.text)
    return {"embedding": vector.tolist()}


@app.post("/embed-many")
def embed_many(payload: EmbedManyRequest) -> dict[str, list[list[float]]]:
    vectors = local_embedding_service.embed_many(payload.texts)
    return {"embeddings": vectors.tolist()}
