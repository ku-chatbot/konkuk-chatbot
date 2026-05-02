from typing import Any, Literal

from pydantic import BaseModel


DisplayFormat = Literal["summary", "table"]


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    route: str
    answer: str
    display_format: DisplayFormat = "summary"
    sql: str | None = None
    rows: list[dict[str, Any]] = []
    sources: list[str] = []
