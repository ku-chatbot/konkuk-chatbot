from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    route: str
    answer: str
    sql: str | None = None
    rows: list[dict[str, Any]] = []
    sources: list[str] = []
