from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.services.openai_client import openai_service


DisplayFormat = Literal["summary", "table"]


@dataclass
class Summary:
    answer: str
    display_format: DisplayFormat


class ResultSummarizer:
    INSTRUCTIONS = (
        "DB 조회 결과를 한국어로 짧고 친절하게 답하세요. "
        "숫자 금액은 쉼표를 넣어 표현하세요. 없는 정보는 꾸며내지 마세요."
    )

    def summarize(self, message: str, rows: list[dict[str, Any]]) -> Summary:
        if len(rows) >= 2:
            return Summary(answer=self._headline(rows), display_format="table")
        return Summary(answer=self._llm_summary(message, rows), display_format="summary")

    def _headline(self, rows: list[dict[str, Any]]) -> str:
        return f"조회 결과 {len(rows)}건입니다."

    def _llm_summary(self, message: str, rows: list[dict[str, Any]]) -> str:
        compact = rows[:8]
        llm = openai_service.complete_text(self.INSTRUCTIONS, f"질문: {message}\n결과: {compact}")
        if llm:
            return llm
        if not compact:
            return "조회 결과가 없습니다."
        parts = [", ".join(f"{k}: {v}" for k, v in row.items()) for row in compact]
        return "조회 결과입니다. " + " / ".join(parts)


result_summarizer = ResultSummarizer()
