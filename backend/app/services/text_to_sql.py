from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.openai_client import openai_service


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
- For student/enrollment/tuition tables, the WHERE clause MUST include
  `student_id = :student_id` (use the bind parameter, never a numeric literal).
- Never write a numeric student_id literal.
- Never expose another student's data.
- Use LIKE with Korean course names when needed.
"""


KNOWN_COURSE_NAMES = (
    "데이터베이스",
    "운영체제",
    "자료구조",
    "알고리즘",
    "컴퓨터네트워크",
    "소프트웨어공학",
    "인공지능",
    "웹프로그래밍",
    "모바일프로그래밍",
    "컴퓨터구조",
    "캡스톤디자인",
    "정보보호",
)


@dataclass
class GeneratedSql:
    sql: str
    params: dict[str, Any]


class TextToSQLService:
    def generate_with_llm(self, message: str) -> GeneratedSql | None:
        llm_sql = self._sql_with_openai(message)
        if not llm_sql:
            return None
        return GeneratedSql(sql=llm_sql, params={})

    def generate_with_rules(self, message: str) -> GeneratedSql | None:
        return self._fallback_sql(message)

    def _sql_with_openai(self, message: str) -> str | None:
        instructions = (
            "You convert Korean university chatbot questions to safe SQLite SQL. "
            'Respond as JSON only: {"answerable": boolean, "sql": string|null, "reason": string}. '
            f"{SCHEMA_DESCRIPTION}"
        )
        data = openai_service.complete_json(instructions, message)
        if not data or not data.get("answerable"):
            return None
        return data.get("sql")

    def _fallback_sql(self, message: str) -> GeneratedSql | None:
        course_filter = self._course_filter(message)
        if "등록금" in message:
            return GeneratedSql(
                sql=(
                    "SELECT semester, amount, payment_status FROM tuition "
                    "WHERE student_id = :student_id ORDER BY semester DESC LIMIT 3"
                ),
                params={},
            )
        if "성적" in message or "학점" in message:
            return GeneratedSql(
                sql=(
                    "SELECT e.semester, c.name AS course_name, e.grade, c.credit "
                    "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
                    "WHERE e.student_id = :student_id ORDER BY e.semester DESC, c.name"
                ),
                params={},
            )
        if "시간표" in message:
            return GeneratedSql(
                sql=(
                    "SELECT c.name AS course_name, s.day_of_week, s.start_time, s.end_time, s.room "
                    "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
                    "JOIN schedule s ON c.course_id = s.course_id "
                    "WHERE e.student_id = :student_id ORDER BY s.day_of_week, s.start_time"
                ),
                params={},
            )
        if "교수" in message or "이메일" in message:
            if course_filter:
                return GeneratedSql(
                    sql=(
                        "SELECT c.name AS course_name, p.name AS professor_name, p.email, p.office "
                        "FROM course c JOIN professor p ON c.professor_id = p.professor_id "
                        "WHERE c.name LIKE :course_pattern ORDER BY c.name LIMIT 10"
                    ),
                    params={"course_pattern": f"%{course_filter}%"},
                )
            return GeneratedSql(
                sql=(
                    "SELECT c.name AS course_name, p.name AS professor_name, p.email, p.office "
                    "FROM course c JOIN enrollment e ON e.course_id = c.course_id "
                    "JOIN professor p ON c.professor_id = p.professor_id "
                    "WHERE e.student_id = :student_id ORDER BY c.name LIMIT 10"
                ),
                params={},
            )
        if "선수" in message:
            if course_filter:
                return GeneratedSql(
                    sql=(
                        "SELECT c.name AS course_name, pre.name AS prerequisite_name "
                        "FROM prerequisite pr JOIN course c ON pr.course_id = c.course_id "
                        "JOIN course pre ON pr.pre_course_id = pre.course_id "
                        "WHERE c.name LIKE :course_pattern ORDER BY c.name"
                    ),
                    params={"course_pattern": f"%{course_filter}%"},
                )
            return GeneratedSql(
                sql=(
                    "SELECT c.name AS course_name, pre.name AS prerequisite_name "
                    "FROM prerequisite pr JOIN course c ON pr.course_id = c.course_id "
                    "JOIN course pre ON pr.pre_course_id = pre.course_id "
                    "ORDER BY c.name"
                ),
                params={},
            )
        if "내 정보" in message or "개인정보" in message or "학과" in message:
            return GeneratedSql(
                sql=(
                    "SELECT student_id, name, major, admission_year, status FROM student "
                    "WHERE student_id = :student_id"
                ),
                params={},
            )
        if "수강" in message or "과목" in message or "강의실" in message:
            return GeneratedSql(
                sql=(
                    "SELECT e.semester, c.name AS course_name, c.credit, c.room, p.name AS professor_name "
                    "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
                    "JOIN professor p ON c.professor_id = p.professor_id "
                    "WHERE e.student_id = :student_id ORDER BY c.name"
                ),
                params={},
            )
        return None

    def _course_filter(self, message: str) -> str | None:
        for name in KNOWN_COURSE_NAMES:
            if name in message:
                return name
        return None


text_to_sql_service = TextToSQLService()
