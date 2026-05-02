from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal

from sqlalchemy.orm import Session

from app.models import Course


Route = Literal["db", "reference_rag", "general"]


@dataclass
class GeneralAnswer:
    answer: str


class GeneralAnswerService:
    DATE_WORDS = ("오늘몇일", "오늘며칠", "오늘날짜", "지금몇일", "지금며칠", "날짜알려", "몇월며칠")
    TIME_WORDS = ("지금몇시", "현재시간", "시간알려")

    def try_answer(self, message: str) -> GeneralAnswer | None:
        compact = message.replace(" ", "")
        if not any(word in compact for word in self.DATE_WORDS + self.TIME_WORDS):
            return None
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
        if any(word in compact for word in self.TIME_WORDS):
            answer = f"지금은 {now.year}년 {now.month}월 {now.day}일 {weekday}요일 {now.hour:02d}:{now.minute:02d}입니다."
        else:
            answer = f"오늘은 {now.year}년 {now.month}월 {now.day}일 {weekday}요일입니다."
        return GeneralAnswer(answer=answer)


class QueryRouter:
    DB_KEYWORDS = ("내", "나의", "수강", "성적", "시간표", "이메일", "강의실", "등록금", "선수과목", "학점", "과목")
    REFERENCE_KEYWORDS = ("휴학", "복학", "장학", "졸업", "신청", "정정", "규정", "교육과정", "전과", "다전공", "출석")

    def classify(self, db: Session, message: str) -> Route:
        course_names = [name for (name,) in db.query(Course.name).all()]
        if any(course in message for course in course_names) and any(k in message for k in self.DB_KEYWORDS):
            return "db"
        if any(k in message for k in self.REFERENCE_KEYWORDS):
            return "reference_rag"
        if any(k in message for k in self.DB_KEYWORDS):
            return "db"
        return "reference_rag"


general_answer_service = GeneralAnswerService()
query_router = QueryRouter()
