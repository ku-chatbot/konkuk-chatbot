from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import AcademicDocument, Course, QueryLog, Student
from app.services.openai_client import openai_service
from app.services.rag_service import rag_service
from app.services.sql_guard import validate_select_sql


SCHEMA_DESCRIPTION = """
Allowed SQLite schema:
- student(student_id, name, major, admission_year, status)
- professor(professor_id, name, email, office)
- course(course_id, name, credit, room, description, professor_id)
- enrollment(enrollment_id, semester, grade, student_id, course_id)
- schedule(schedule_id, day_of_week, start_time, end_time, room, course_id)
- tuition(tuition_id, semester, amount, payment_status, student_id)
- prerequisite(id, course_id, pre_course_id)
Rules:
- Return a single SELECT query only.
- Use :student_id for the logged-in student.
- Never expose another student's data.
- Use LIKE with Korean course names when needed.
"""


@dataclass
class QueryResult:
    route: str
    answer: str
    sql: str | None = None
    rows: list[dict[str, Any]] | None = None
    sources: list[str] | None = None


class QueryService:
    def answer(self, db: Session, student: Student, message: str) -> QueryResult:
        general = self._answer_general(message)
        if general:
            self._log(db, student.student_id, message, general.route, None, True, None)
            return general
        route = self._decide_route(db, message)
        if route == "db":
            result = self._answer_from_db(db, student, message)
            if result:
                self._log(db, student.student_id, message, "db", result.sql, True, None)
                return result
        rag = rag_service.answer(db, message)
        self._log(db, student.student_id, message, "rag", None, True, None)
        return rag

    def schema(self) -> dict[str, Any]:
        return {
            "tables": {
                "student": ["student_id", "name", "major", "admission_year", "status"],
                "professor": ["professor_id", "name", "email", "office"],
                "course": ["course_id", "name", "credit", "room", "description", "professor_id"],
                "enrollment": ["enrollment_id", "semester", "grade", "student_id", "course_id"],
                "schedule": ["schedule_id", "day_of_week", "start_time", "end_time", "room", "course_id"],
                "tuition": ["tuition_id", "semester", "amount", "payment_status", "student_id"],
                "prerequisite": ["id", "course_id", "pre_course_id"],
            }
        }

    def execute_sql(self, db: Session, student: Student, sql: str) -> list[dict[str, Any]]:
        ok, reason = validate_select_sql(sql)
        if not ok:
            raise ValueError(reason)
        return [dict(row._mapping) for row in db.execute(text(sql), {"student_id": student.student_id}).fetchall()]

    def _decide_route(self, db: Session, message: str) -> str:
        db_keywords = ["내", "나의", "수강", "성적", "시간표", "교수", "이메일", "강의실", "등록금", "선수과목", "학점", "과목"]
        academic_keywords = ["휴학", "복학", "장학", "졸업", "신청", "정정", "규정", "교육과정", "전과", "다전공", "출석"]
        course_names = [name for (name,) in db.query(Course.name).all()]
        if any(course in message for course in course_names) and any(k in message for k in db_keywords):
            return "db"
        if any(k in message for k in academic_keywords) and not any(k in message for k in ["내", "나의", "얼마", "보여", "알려"]):
            return "rag"
        if any(k in message for k in db_keywords):
            return "db"
        if db.query(AcademicDocument).filter(AcademicDocument.content.contains(message[:8])).first():
            return "rag"
        return "rag"

    def _answer_general(self, message: str) -> QueryResult | None:
        compact = message.replace(" ", "")
        date_words = ["오늘몇일", "오늘며칠", "오늘날짜", "지금몇일", "지금며칠", "날짜알려", "몇월며칠"]
        time_words = ["지금몇시", "현재시간", "시간알려"]
        if any(word in compact for word in date_words + time_words):
            now = datetime.now(ZoneInfo("Asia/Seoul"))
            weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
            if any(word in compact for word in time_words):
                answer = f"지금은 {now.year}년 {now.month}월 {now.day}일 {weekday}요일 {now.hour:02d}:{now.minute:02d}입니다."
            else:
                answer = f"오늘은 {now.year}년 {now.month}월 {now.day}일 {weekday}요일입니다."
            return QueryResult(route="general", answer=answer, rows=[], sources=[])
        return None

    def _answer_from_db(self, db: Session, student: Student, message: str) -> QueryResult | None:
        sql = self._sql_with_openai(message)
        if sql:
            ok, _ = validate_select_sql(sql)
            if ok:
                try:
                    rows = self.execute_sql(db, student, sql)
                    if rows:
                        return QueryResult(route="db", answer=self._summarize_rows(message, rows), sql=sql, rows=rows, sources=[])
                except Exception:
                    pass
        fallback_sql = self._fallback_sql(message)
        if not fallback_sql:
            return None
        rows = self.execute_sql(db, student, fallback_sql)
        if not rows:
            return QueryResult(route="db", answer="조회 결과가 없습니다. 질문의 과목명이나 학기를 조금 더 구체적으로 적어주세요.", sql=fallback_sql, rows=[], sources=[])
        return QueryResult(route="db", answer=self._summarize_rows(message, rows), sql=fallback_sql, rows=rows, sources=[])

    def _sql_with_openai(self, message: str) -> str | None:
        instructions = (
            "You convert Korean university chatbot questions to safe SQLite SQL. "
            "Respond as JSON only: {\"answerable\": boolean, \"sql\": string|null, \"reason\": string}. "
            f"{SCHEMA_DESCRIPTION}"
        )
        data = openai_service.complete_json(instructions, message)
        if not data or not data.get("answerable"):
            return None
        return data.get("sql")

    def _fallback_sql(self, message: str) -> str | None:
        course_filter = self._course_filter(message)
        if "등록금" in message:
            return "SELECT semester, amount, payment_status FROM tuition WHERE student_id = :student_id ORDER BY semester DESC LIMIT 3"
        if "성적" in message or "학점" in message:
            return (
                "SELECT e.semester, c.name AS course_name, e.grade, c.credit "
                "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
                "WHERE e.student_id = :student_id ORDER BY e.semester DESC, c.name"
            )
        if "시간표" in message:
            return (
                "SELECT c.name AS course_name, s.day_of_week, s.start_time, s.end_time, s.room "
                "FROM enrollment e JOIN course c ON e.course_id = c.course_id JOIN schedule s ON c.course_id = s.course_id "
                "WHERE e.student_id = :student_id ORDER BY s.day_of_week, s.start_time"
            )
        if "교수" in message or "이메일" in message:
            where = f"WHERE c.name LIKE '%{course_filter}%'" if course_filter else "WHERE e.student_id = :student_id"
            join = "JOIN enrollment e ON e.course_id = c.course_id " if not course_filter else ""
            return (
                "SELECT c.name AS course_name, p.name AS professor_name, p.email, p.office "
                f"FROM course c {join}JOIN professor p ON c.professor_id = p.professor_id {where} "
                "ORDER BY c.name LIMIT 10"
            )
        if "선수" in message:
            where = f"WHERE c.name LIKE '%{course_filter}%'" if course_filter else ""
            return (
                "SELECT c.name AS course_name, pre.name AS prerequisite_name "
                "FROM prerequisite pr JOIN course c ON pr.course_id = c.course_id "
                f"JOIN course pre ON pr.pre_course_id = pre.course_id {where} ORDER BY c.name"
            )
        if "내 정보" in message or "개인정보" in message or "학과" in message:
            return "SELECT student_id, name, major, admission_year, status FROM student WHERE student_id = :student_id"
        if "수강" in message or "과목" in message or "강의실" in message:
            return (
                "SELECT e.semester, c.name AS course_name, c.credit, c.room, p.name AS professor_name "
                "FROM enrollment e JOIN course c ON e.course_id = c.course_id JOIN professor p ON c.professor_id = p.professor_id "
                "WHERE e.student_id = :student_id ORDER BY c.name"
            )
        return None

    def _course_filter(self, message: str) -> str | None:
        known = ["데이터베이스", "운영체제", "자료구조", "알고리즘", "컴퓨터네트워크", "소프트웨어공학", "인공지능", "웹프로그래밍", "모바일프로그래밍", "컴퓨터구조", "캡스톤디자인", "정보보호"]
        for name in known:
            if name in message:
                return name
        return None

    def _summarize_rows(self, message: str, rows: list[dict[str, Any]]) -> str:
        compact = rows[:8]
        instructions = "DB 조회 결과를 한국어로 짧고 친절하게 답하세요. 숫자 금액은 쉼표를 넣어 표현하세요. 없는 정보는 꾸며내지 마세요."
        llm = openai_service.complete_text(instructions, f"질문: {message}\n결과: {compact}")
        if llm:
            return llm
        parts = []
        for row in compact:
            parts.append(", ".join(f"{k}: {v}" for k, v in row.items()))
        suffix = f" 외 {len(rows) - len(compact)}건" if len(rows) > len(compact) else ""
        return "조회 결과입니다. " + " / ".join(parts) + suffix

    def _log(self, db: Session, student_id: int, message: str, route: str, sql: str | None, success: bool, error: str | None) -> None:
        db.add(QueryLog(student_id=student_id, message=message, route=route, generated_sql=sql, success=success, error=error))
        db.commit()


query_service = QueryService()
