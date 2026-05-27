from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, aliased

from app.models import ConversationState, Course, CoursePrerequisiteNote, Enrollment, Prerequisite, Professor, QueryLog, Student
from app.services.openai_client import openai_service
from app.services.progress_service import progress_service
from app.services.reference_rag_service import reference_rag_service
from app.services.sql_guard import validate_select_sql
from app.services.web_search_service import web_search_service


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


@dataclass
class QueryUnderstanding:
    domain: str
    domains: list[str]
    intent: str
    entities: list[str]
    explicit_domain: bool = False
    is_followup_candidate: bool = False


class QueryService:
    def answer(self, db: Session, student: Student, message: str, request_id: str | None = None) -> QueryResult:
        self._emit(request_id, "start", "질문을 분류하고 있습니다.", "DB, 공식문서, 웹검색 중 어디를 볼지 판단합니다.")
        understanding = self._understand_query(message)
        general = self._answer_general(message)
        if general:
            self._log(db, student.student_id, message, general.route, None, True, None)
            return general
        event = self._answer_event_question(message)
        if event:
            self._log(db, student.student_id, message, event.route, None, True, None)
            return event
        state_message = self._apply_conversation_state(db, student, message, understanding)
        if state_message != message:
            effective_message = state_message
        else:
            effective_message = message if self._is_explicit_db_question(db, message) else self._contextualize_followup(db, student, message, understanding)
        effective_understanding = self._understand_query(effective_message)
        privacy = self._privacy_violation(db, student, f"{message}\n{effective_message}")
        if privacy:
            self._log(db, student.student_id, message, privacy.route, None, True, None)
            return privacy
        clarification = self._clarify_ambiguous_question(effective_message)
        if clarification:
            self._log(db, student.student_id, message, clarification.route, None, True, None)
            return clarification
        sourced = self._answer_with_source_planner(db, student, effective_message, effective_understanding, request_id=request_id)
        if sourced:
            self._update_conversation_state(db, student.student_id, effective_message, sourced.route)
            self._log(db, student.student_id, message, sourced.route, sourced.sql, True, None)
            return sourced
        planned = self._answer_with_planner(db, student, effective_message, request_id=request_id)
        if planned:
            self._update_conversation_state(db, student.student_id, effective_message, planned.route)
            self._log(db, student.student_id, message, planned.route, None, True, None)
            return planned
        route = self._decide_route(db, effective_message)
        if route == "db":
            self._emit(request_id, "db", "내부 학사 DB를 조회하고 있습니다.", "성적, 시간표, 과목, 교수 정보를 확인합니다.")
            result = self._answer_from_db(db, student, effective_message)
            if result:
                self._update_conversation_state(db, student.student_id, effective_message, "db")
                self._log(db, student.student_id, message, "db", result.sql, True, None)
                return result
        if route == "reference_rag":
            self._emit(request_id, "reference_rag", "공식 학사문서를 검색하고 있습니다.", "관련 문서 조각을 찾고 출처를 확인합니다.", self._progress_keywords([effective_message]))
            rag = reference_rag_service.answer(db, effective_message, domain=effective_understanding.domain, domains=effective_understanding.domains, intent=effective_understanding.intent)
            self._update_conversation_state(db, student.student_id, effective_message, "reference_rag")
            self._log(db, student.student_id, message, "reference_rag", None, True, None)
            return QueryResult(route=rag.route, answer=rag.answer, rows=[], sources=rag.sources)
        if route == "web_search":
            self._emit(request_id, "web_search", "건국대학교 공식 페이지를 검색하고 있습니다.", "최신 공지나 홈페이지 정보를 확인합니다.", self._progress_keywords([effective_message]))
            web = web_search_service.answer(effective_message)
            self._update_conversation_state(db, student.student_id, effective_message, "web_search")
            self._log(db, student.student_id, message, "web_search", None, True, None)
            return QueryResult(route=web.route, answer=web.answer, rows=[], sources=web.sources)
        result = QueryResult(route="general", answer="내부 DB나 공식 참고문서에서 확인할 수 있도록 질문을 조금 더 구체적으로 적어주세요.", rows=[], sources=[])
        self._log(db, student.student_id, message, result.route, None, True, None)
        return result

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

    def _emit(
        self,
        request_id: str | None,
        stage: str,
        label: str,
        detail: str | None = None,
        keywords: list[str] | None = None,
    ) -> None:
        progress_service.update(request_id, stage=stage, label=label, detail=detail, keywords=keywords or [])

    def _understand_query(self, message: str) -> QueryUnderstanding:
        compact = message.replace(" ", "")
        domains = [
            ("leave", ["휴학", "입대휴학", "가사휴학", "질병휴학", "육아휴학", "창업휴학", "미등록"]),
            ("return", ["복학"]),
            ("graduation", ["졸업", "졸업요건", "졸업유예", "졸업가능", "졸업시뮬레이션"]),
            ("course_registration", ["수강신청", "수강정정", "수강바구니", "계절학기", "전공인정", "학점인정"]),
            ("scholarship", ["장학", "장학금", "장학복지팀"]),
            ("tuition", ["등록금", "납부"]),
            ("grade", ["성적", "평점", "학점"]),
            ("schedule", ["시간표"]),
            ("professor", ["교수", "교수님", "학과장", "학부장", "연구실", "이메일"]),
            ("course", ["과목", "수업", "강의실", "선수", "선수과목"]),
            ("international", ["교환학생", "국제교류"]),
            ("event", ["축제", "행사", "일정", "쉬는날", "휴일", "공휴일", "선거날", "선거일"]),
        ]
        matched_domains = []
        for candidate, keywords in domains:
            if any(keyword in compact for keyword in keywords):
                matched_domains.append(candidate)
        domain = matched_domains[0] if matched_domains else "unknown"
        explicit_domain = bool(matched_domains)

        if self._is_course_grading_policy_question(message):
            intent = "course_grading_policy"
            if "course" not in matched_domains:
                matched_domains.insert(0, "course")
            if "grade" in matched_domains:
                matched_domains = [domain for domain in matched_domains if domain != "grade"]
        elif "이메일" in compact:
            intent = "email"
        elif any(word in compact for word in ["연구실", "사무실", "office"]):
            intent = "office"
        elif "강의실" in compact:
            intent = "classroom"
        elif any(word in compact for word in ["언제", "언제까지", "기간", "몇일까지", "마감"]):
            intent = "deadline"
        elif any(word in compact for word in ["어디", "경로", "링크", "홈페이지", "사이트", "확인", "조회", "보려면"]):
            intent = "location"
        elif any(word in compact for word in ["서류", "준비물", "필요"]):
            intent = "documents"
        elif any(word in compact for word in ["방법", "어떻게", "하는법", "신청"]):
            intent = "method"
        elif any(word in compact for word in ["몇번", "몇회", "가능횟수", "얼마나"]):
            intent = "count"
        elif self._is_course_recommendation_question(message):
            intent = "recommendation"
        elif any(word in compact for word in ["전공인정", "인정돼", "인정되", "인정받", "학점인정"]):
            intent = "credit_recognition"
        else:
            intent = "lookup"

        entities = self._progress_keywords([message])
        followup_words = ["그럼", "그러면", "그건", "그거", "이건", "이거", "어디", "언제", "서류", "필요", "2학기", "1학기", "미등록"]
        is_followup_candidate = len(compact) <= 30 and any(word in compact for word in followup_words)
        return QueryUnderstanding(
            domain=domain,
            domains=matched_domains or ["unknown"],
            intent=intent,
            entities=entities,
            explicit_domain=explicit_domain,
            is_followup_candidate=is_followup_candidate,
        )

    def _apply_conversation_state(self, db: Session, student: Student, message: str, current: QueryUnderstanding) -> str:
        state = db.query(ConversationState).filter(ConversationState.student_id == student.student_id).first()
        if state is None:
            return message
        entities = self._state_entities(state)
        if not entities:
            return message
        compact = message.replace(" ", "")
        has_course = bool(self._course_filter(db, message))
        has_professor = self._professor_in_message(db, message) is not None
        short_entityless = len(compact) <= 20 and not has_course and not has_professor
        if not short_entityless:
            return message

        course = entities.get("course")
        professor = entities.get("professor")
        if any(word in compact for word in ["연구실", "사무실", "office"]) and (professor or course):
            if professor:
                return f"{professor} 교수님 연구실 알려줘"
            return f"{course} 교수님 연구실 알려줘"
        if "이메일" in compact and (professor or course):
            if professor:
                return f"{professor} 교수님 이메일 알려줘"
            return f"{course} 교수님 이메일 알려줘"
        if "강의실" in compact and course:
            return f"{course} 강의실 알려줘"
        if any(word in compact for word in ["교수", "교수님"]) and course:
            return f"{course} 교수님 알려줘"
        return message

    def _state_entities(self, state: ConversationState) -> dict[str, str]:
        try:
            raw = json.loads(state.entities_json or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items() if value}

    def _update_conversation_state(self, db: Session, student_id: int, message: str, route: str) -> None:
        understanding = self._understand_query(message)
        entities = self._extract_state_entities(db, message)
        if not entities and understanding.domain == "unknown":
            return
        state = db.query(ConversationState).filter(ConversationState.student_id == student_id).first()
        if state is None:
            state = ConversationState(student_id=student_id)
            db.add(state)
        previous_entities = self._state_entities(state)
        if entities:
            merged_entities = {**previous_entities, **entities}
        elif understanding.domain != state.domain:
            merged_entities = {}
        else:
            merged_entities = previous_entities
        state.domain = understanding.domain
        state.intent = understanding.intent
        state.entities_json = json.dumps(merged_entities, ensure_ascii=False)
        state.last_question = message
        state.last_route = route
        db.commit()

    def _extract_state_entities(self, db: Session, message: str) -> dict[str, str]:
        entities: dict[str, str] = {}
        course_name = self._course_filter(db, message)
        professor = self._professor_in_message(db, message)
        if course_name:
            entities["course"] = course_name
            professor_name = (
                db.query(Professor.name)
                .join(Course, Course.professor_id == Professor.professor_id)
                .filter(Course.name.contains(course_name))
                .order_by(Course.name)
                .limit(1)
                .scalar()
            )
            if professor_name:
                entities["professor"] = professor_name
        if professor:
            entities["professor"] = professor.name
        return entities

    def execute_sql(self, db: Session, student: Student, sql: str) -> list[dict[str, Any]]:
        ok, reason = validate_select_sql(sql)
        if not ok:
            raise ValueError(reason)
        return [dict(row._mapping) for row in db.execute(text(sql), {"student_id": student.student_id}).fetchall()]

    def _decide_route(self, db: Session, message: str) -> str:
        db_keywords = ["내", "나의", "성적", "시간표", "교수", "교수님", "이메일", "연구실", "강의실", "등록금", "선수", "선수과목", "학점"]
        academic_keywords = ["휴학", "복학", "장학", "졸업", "신청", "정정", "규정", "교육과정", "전과", "다전공", "출석", "국제교류", "교환학생"]
        course_names = [name for (name,) in db.query(Course.name).all()]
        if "선수" in message:
            return "db"
        if self._is_holiday_question(message):
            return "web_search"
        if self._is_web_search_question(message):
            return "web_search"
        if self._is_academic_policy_question(message):
            return "reference_rag"
        if self._is_db_lookup_question(db, message):
            return "db"
        if self._professor_in_message(db, message) and any(k in message for k in db_keywords):
            return "db"
        if any(k in message for k in academic_keywords):
            return "reference_rag"
        if any(k in message for k in db_keywords):
            return "db"
        return "unknown"

    def _is_explicit_db_question(self, db: Session, message: str) -> bool:
        compact = message.replace(" ", "")
        if self._is_academic_policy_question(message) or self._is_course_recommendation_question(message):
            return False
        db_keywords = ["내성적", "나의성적", "내시간표", "나의시간표", "내수강", "나의수강", "내등록금", "나의등록금", "교수", "교수님", "이메일", "연구실", "강의실", "선수", "선수과목"]
        if any(keyword in compact for keyword in db_keywords):
            return True
        if self._professor_in_message(db, message):
            return True
        if any(alias in compact for alias in self._course_aliases()):
            return True
        return self._is_db_lookup_question(db, message)

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

    def _answer_event_question(self, message: str) -> QueryResult | None:
        if "축제" not in message:
            return None
        if web_search_service.is_enabled():
            web = web_search_service.answer(message)
            return QueryResult(route=web.route, answer=web.answer, rows=[], sources=web.sources)
        return QueryResult(
            route="reference_rag",
            answer="현재 연결된 학사 DB와 참고문서에서는 축제 일정을 확인할 수 없습니다. 축제 일정은 매년 바뀌는 행사 정보라 건국대학교 홈페이지 공지사항이나 총학생회 공지를 확인해주세요.",
            rows=[],
            sources=[],
        )

    def _clarify_ambiguous_question(self, message: str) -> QueryResult | None:
        compact = message.strip().replace(" ", "")
        if compact in {"학점", "학점알려줘", "내학점", "나의학점"}:
            return QueryResult(
                route="general",
                answer="말씀하신 `학점`이 성적 평점인지, 이수학점/취득학점인지 구분이 필요해요. 예: `내 성적 알려줘`, `내 이수학점 알려줘`",
                rows=[],
                sources=[],
            )
        return None

    def _is_web_search_question(self, message: str) -> bool:
        compact = message.replace(" ", "")
        web_keywords = [
            "최신",
            "현재",
            "지금",
            "누구",
            "누가",
            "학과장",
            "처장",
            "총장",
            "공지",
            "공지사항",
            "홈페이지",
            "사이트",
            "링크",
            "축제",
            "행사",
            "일정",
            "위치",
            "주소",
            "전화번호",
            "연락처",
            "운영시간",
            "센터",
            "부서",
            "기관",
            "교수진",
            "교수소개",
        ]
        school_terms = ["건국대", "건국대학교", "컴퓨터공학부", "컴공", "konkuk", "KU"]
        chair_terms = ["학과장", "학부장"]
        if any(keyword in compact for keyword in chair_terms):
            return True
        if self._is_course_offering_web_question(message):
            return True
        return any(keyword in compact for keyword in web_keywords) and any(term in message for term in school_terms)

    def _is_course_offering_web_question(self, message: str) -> bool:
        compact = message.replace(" ", "")
        has_term = any(word in compact for word in ["다음학기", "이번학기", "내년", "2026", "2027", "하계계절", "동계계절", "계절학기"])
        asks_offering = any(word in compact for word in ["개설강좌", "개설과목", "강의시간표", "종합강의시간표", "어떤수업", "무슨수업", "수업들이열", "열려", "열리는수업"])
        has_department = any(word in compact for word in ["컴퓨터공학", "컴공", "학과", "학부", "전공"])
        return has_term and asks_offering and has_department

    def _is_holiday_question(self, message: str) -> bool:
        compact = message.replace(" ", "")
        return any(word in compact for word in ["쉬는날", "휴일", "공휴일", "선거날", "선거일"]) and (
            bool(re.search(r"\d+월\d+일", compact)) or "선거" in compact or "학교" in compact or "건국" in compact
        )

    def _is_academic_policy_question(self, message: str) -> bool:
        compact = message.replace(" ", "")
        policy_words = [
            "계절학기",
            "전공인정",
            "인정돼",
            "인정되",
            "인정받",
            "이수구분",
            "전공학점",
            "학점인정",
            "수강신청",
            "수강정정",
            "수강바구니",
            "졸업요건",
            "졸업유예",
        ]
        return any(word in compact for word in policy_words)

    def _is_course_recommendation_question(self, message: str) -> bool:
        compact = message.replace(" ", "")
        return any(word in compact for word in ["추천", "관심", "들을만한", "수강할만한", "뭐들을"]) and any(word in compact for word in ["과목", "수업", "수강"])

    def _is_course_grading_policy_question(self, message: str) -> bool:
        compact = message.replace(" ", "")
        grading_words = ["성적비율", "평가비율", "평가방법", "평가기준", "성적평가", "중간고사", "기말고사", "과제", "출석", "시험비율"]
        return any(word in compact for word in grading_words)

    def _is_db_lookup_question(self, db: Session, message: str) -> bool:
        compact = message.replace(" ", "")
        if self._is_course_grading_policy_question(message):
            return False
        if self._is_department_professor_list_question(message):
            return True
        if any(word in compact for word in ["내성적", "나의성적", "저번학기성적", "이번학기성적", "내시간표", "오늘시간표", "내수강", "내등록금", "나의등록금"]):
            return True
        if any(word in compact for word in ["강의실", "이메일", "연구실"]):
            return True
        if "교수" in compact or "교수님" in compact:
            return True
        if "학점" in compact and any(word in compact for word in ["성적", "평점", "이수", "취득"]):
            return True
        course_names = [name for (name,) in db.query(Course.name).all()]
        return any(course in message for course in course_names) and any(word in compact for word in ["강의실", "교수", "교수님", "선수"])

    def _is_department_professor_list_question(self, message: str) -> bool:
        compact = message.replace(" ", "")
        asks_list = any(word in compact for word in ["교수목록", "교수진", "교수리스트", "교수님목록", "교수명단"])
        department = any(word in compact for word in ["컴퓨터공학", "컴공", "컴퓨터공학부", "컴퓨터공학과"])
        return asks_list and department

    def _answer_with_source_planner(
        self,
        db: Session,
        student: Student,
        message: str,
        understanding: QueryUnderstanding,
        request_id: str | None = None,
    ) -> QueryResult | None:
        candidates = self._source_candidates(db, message, understanding)
        if not candidates:
            return None
        self._emit(
            request_id,
            "source_planner",
            "답변 근거를 찾을 위치를 정하고 있습니다.",
            "질문 의도에 맞는 후보 소스만 확인합니다.",
            candidates,
        )
        for candidate in candidates:
            if candidate == "syllabus_rag":
                return self._answer_from_syllabus_placeholder(db, message)
            if candidate == "planned":
                planned = self._answer_with_planner(db, student, message, request_id=request_id)
                if planned and self._is_answerable(planned):
                    return planned
                continue
            if candidate == "db":
                self._emit(request_id, "db", "내부 학사 DB를 조회하고 있습니다.", "질문 의도와 맞는 DB 근거만 확인합니다.")
                result = self._answer_from_db(db, student, message)
                if result and self._is_answerable(result):
                    return result
                continue
            if candidate == "reference_rag":
                self._emit(request_id, "reference_rag", "공식 학사문서를 검색하고 있습니다.", "질문 주제와 맞는 문서 근거만 확인합니다.", self._progress_keywords([message]))
                rag = reference_rag_service.answer(db, message, domain=understanding.domain, domains=understanding.domains, intent=understanding.intent)
                result = QueryResult(route=rag.route, answer=rag.answer, rows=[], sources=rag.sources)
                if self._is_answerable(result):
                    return result
                continue
            if candidate == "web_search":
                self._emit(request_id, "web_search", "건국대학교 공식 페이지를 검색하고 있습니다.", "최신 공식 홈페이지 근거를 확인합니다.", self._progress_keywords([message]))
                web = web_search_service.answer(message)
                result = QueryResult(route=web.route, answer=web.answer, rows=[], sources=web.sources)
                if self._is_answerable(result) or "웹검색이 필요한 질문" in result.answer:
                    return result
        return None

    def _source_candidates(self, db: Session, message: str, understanding: QueryUnderstanding) -> list[str]:
        if self._is_course_grading_policy_question(message):
            return ["syllabus_rag"]
        if self._is_course_recommendation_question(message):
            return ["planned"]
        if self._is_course_offering_web_question(message):
            return ["web_search"]
        if understanding.domain == "course_registration" and understanding.intent in {"deadline", "location", "method", "lookup"}:
            return ["reference_rag"]
        if self._needs_planner(db, message):
            return ["planned", "reference_rag"]
        if self._is_web_search_question(message) or self._is_holiday_question(message):
            return ["web_search"]
        if understanding.domain in {"leave", "return", "graduation", "course_registration", "scholarship", "international"}:
            return ["reference_rag"]
        if self._is_db_lookup_question(db, message):
            return ["db"]
        if understanding.domain in {"grade", "schedule", "tuition", "professor", "course"}:
            return ["db"]
        return []

    def _is_answerable(self, result: QueryResult) -> bool:
        unanswerable_markers = [
            "확인하지 못했습니다",
            "찾지 못했습니다",
            "조금 더 구체적으로",
            "요청을 처리하지 못했습니다",
        ]
        if result.sources:
            return True
        if result.rows:
            return True
        return not any(marker in result.answer for marker in unanswerable_markers)

    def _answer_from_syllabus_placeholder(self, db: Session, message: str) -> QueryResult:
        course_name = self._course_filter(db, message)
        subject = f"{course_name}의 " if course_name else ""
        return QueryResult(
            route="syllabus_rag",
            answer=(
                f"{subject}성적 비율/평가방법은 강의계획서의 평가 항목에서 확인해야 합니다. "
                "현재 연결된 강의계획서 RAG 데이터가 없어 정확한 평가 비율은 확인할 수 없습니다. "
                "강의계획서 데이터를 인제스트하면 중간고사, 기말고사, 과제, 출석 같은 평가 비율을 근거 기반으로 답변할 수 있습니다."
            ),
            rows=[],
            sources=[],
        )

    def _answer_with_planner(self, db: Session, student: Student, message: str, request_id: str | None = None) -> QueryResult | None:
        if not self._needs_planner(db, message):
            return None
        self._emit(request_id, "planner", "질문을 여러 근거로 나눠 보고 있습니다.", "과목 DB, 공식문서, 필요 시 웹검색을 조합합니다.")
        plan = self._plan_complex_question(db, message)
        if not plan or not plan.get("is_complex"):
            plan = self._fallback_plan(message, db)

        plan_keywords = self._planner_keywords(plan)
        self._emit(
            request_id,
            "planner",
            "검색 계획을 세웠습니다.",
            "이 키워드로 DB와 문서 근거를 모읍니다.",
            plan_keywords,
        )
        self._emit(
            request_id,
            "planner_db",
            "과목 DB를 확인하고 있습니다.",
            "개설 과목, 학점, 이수구분, 담당교수를 확인합니다.",
            self._progress_keywords(plan.get("course_names") or [message]),
        )
        course_evidence = self._planner_course_evidence(db, plan)
        rag_evidence = self._planner_rag_evidence(db, plan, request_id=request_id)
        web_evidence = self._planner_web_evidence(plan, request_id=request_id)
        self._emit(request_id, "planner_answer", "근거를 합쳐 답변을 작성하고 있습니다.", "확인된 내용과 확인이 필요한 내용을 나눠 정리합니다.", plan_keywords)
        answer = self._synthesize_planned_answer(message, plan, course_evidence, rag_evidence, web_evidence)
        sources = []
        for item in rag_evidence:
            sources.extend(item.get("sources", []))
        for item in web_evidence:
            sources.extend(item.get("sources", []))
        return QueryResult(route="planned", answer=answer, rows=course_evidence, sources=list(dict.fromkeys(sources)))

    def _needs_planner(self, db: Session, message: str) -> bool:
        if self._is_course_recommendation_question(message):
            return True
        if self._is_academic_policy_question(message):
            course_names = [name for (name,) in db.query(Course.name).all()]
            return any(course in message for course in course_names) or any(word in message for word in ["과목", "수강", "전공", "계절"])
        return False

    def _plan_complex_question(self, db: Session, message: str) -> dict[str, Any] | None:
        course_names = [name for (name,) in db.query(Course.name).order_by(Course.name).all()]
        instructions = (
            "사용자의 대학 챗봇 질문이 여러 근거(DB 과목정보, 공식문서, 최신 웹공지)를 조합해야 하는 복합 질문인지 판단하세요. "
            "반드시 JSON만 반환하세요. "
            "스키마: {\"is_complex\": boolean, \"intent\": \"credit_recognition|course_recommendation|other\", "
            "\"course_names\": string[], \"rag_queries\": string[], \"web_query\": string|null, \"needs_web\": boolean, \"reason\": string}. "
            "course_names는 제공된 개설 과목명 중 질문에 관련된 과목만 넣으세요. "
            "rag_queries는 공식 학사문서에서 찾아야 할 규정 질문 1~3개로 만드세요."
        )
        data = openai_service.complete_json(instructions, f"질문: {message}\n개설 과목명: {course_names}")
        if data and data.get("is_complex"):
            return data
        if data and self._is_course_recommendation_question(message):
            data["is_complex"] = True
            data["intent"] = "course_recommendation"
            data.setdefault("course_names", [])
            data.setdefault("rag_queries", [message])
            data.setdefault("web_query", None)
            data.setdefault("needs_web", False)
            return data
        if data and self._is_academic_policy_question(message):
            data["is_complex"] = True
            data.setdefault("intent", "credit_recognition")
            data.setdefault("rag_queries", [message])
            return data
        return self._fallback_plan(message, db)

    def _fallback_plan(self, message: str, db: Session) -> dict[str, Any]:
        course_name = self._course_filter(db, message)
        return {
            "is_complex": True,
            "intent": "course_recommendation" if self._is_course_recommendation_question(message) else "credit_recognition",
            "course_names": [course_name] if course_name else [],
            "rag_queries": [message],
            "web_query": f"건국대학교 {message}",
            "needs_web": self._is_academic_policy_question(message),
            "reason": "fallback planner",
        }

    def _planner_course_evidence(self, db: Session, plan: dict[str, Any]) -> list[dict[str, Any]]:
        requested = [name for name in plan.get("course_names", []) if isinstance(name, str)]
        query = db.query(Course.name, Course.credit, Course.room, Course.description, Professor.name.label("professor_name")).join(Professor)
        if plan.get("intent") == "course_recommendation":
            rows = query.order_by(Course.name).limit(80).all()
        elif requested:
            filters = [Course.name.contains(name) for name in requested]
            rows = query.filter(*filters).order_by(Course.name).limit(20).all() if len(filters) == 1 else query.filter(Course.name.in_(requested)).order_by(Course.name).limit(20).all()
        else:
            rows = []
        evidence = []
        for row in rows:
            evidence.append(
                {
                    "course_name": row.name,
                    "credit": row.credit,
                    "professor": row.professor_name,
                    "room": row.room,
                    "category": self._course_category(row.description),
                    "description": row.description,
                }
            )
        return evidence

    def _planner_keywords(self, plan: dict[str, Any]) -> list[str]:
        values: list[str] = []
        values.extend([item for item in plan.get("course_names", []) if isinstance(item, str)])
        values.extend([item for item in plan.get("rag_queries", []) if isinstance(item, str)])
        if isinstance(plan.get("web_query"), str):
            values.append(plan["web_query"])
        return self._progress_keywords(values)

    def _progress_keywords(self, values: list[str]) -> list[str]:
        keywords: list[str] = []
        for value in values:
            for token in re.findall(r"[가-힣A-Za-z0-9]+", value):
                if len(token) < 2:
                    continue
                if token in {"알려줘", "어떻게", "있습니다", "합니다", "질문"}:
                    continue
                keywords.append(token)
        return list(dict.fromkeys(keywords))[:8]

    def _planner_rag_evidence(self, db: Session, plan: dict[str, Any], request_id: str | None = None) -> list[dict[str, Any]]:
        evidence = []
        for query in (plan.get("rag_queries") or [])[:3]:
            if not isinstance(query, str) or not query.strip():
                continue
            self._emit(
                request_id,
                "planner_rag",
                "공식 학사문서를 검색하고 있습니다.",
                "규정이나 신청 절차에 필요한 근거를 찾습니다.",
                self._progress_keywords([query]),
            )
            rag = reference_rag_service.answer(db, query)
            if rag.sources and "확인하지 못했습니다" not in rag.answer:
                evidence.append({"query": query, "answer": rag.answer, "sources": rag.sources})
        return evidence

    def _planner_web_evidence(self, plan: dict[str, Any], request_id: str | None = None) -> list[dict[str, Any]]:
        if not plan.get("needs_web") or not plan.get("web_query"):
            return []
        self._emit(
            request_id,
            "planner_web",
            "공식 홈페이지를 검색하고 있습니다.",
            "문서에 없는 최신성 정보를 확인합니다.",
            self._progress_keywords([str(plan["web_query"])]),
        )
        web = web_search_service.answer(str(plan["web_query"]))
        if web.sources:
            return [{"query": plan["web_query"], "answer": web.answer, "sources": web.sources}]
        return []

    def _synthesize_planned_answer(self, message: str, plan: dict[str, Any], course_evidence: list[dict[str, Any]], rag_evidence: list[dict[str, Any]], web_evidence: list[dict[str, Any]]) -> str:
        instructions = (
            "대학 챗봇 답변을 작성하세요. 제공된 근거만 사용하고 모르는 내용은 확인 필요하다고 말하세요. "
            "course_evidence는 현재 DB에 실제로 존재하는 개설 과목 정보입니다. course_evidence에 있는 과목을 없거나 확인 필요하다고 말하지 마세요. "
            "과목 추천 질문은 course_evidence 안에서만 추천하고, 추천 이유를 과목명과 이수구분 중심으로 짧게 설명하세요. "
            "Markdown 강조(**, __)를 쓰지 마세요. 짧고 자연스럽게 답하세요. "
            "답변 가능 여부가 부분적이면 확인된 내용과 확인이 필요한 내용을 분리하세요."
        )
        payload = {
            "question": message,
            "plan": plan,
            "course_evidence": course_evidence,
            "official_document_evidence": rag_evidence,
            "web_evidence": web_evidence,
        }
        answer = openai_service.complete_text(instructions, str(payload))
        if answer:
            return self._clean_llm_db_answer(answer)
        if course_evidence:
            lines = ["확인된 과목 정보입니다."]
            for course in course_evidence[:5]:
                category = f", {course['category']}" if course.get("category") else ""
                lines.append(f"- {course['course_name']}: {course['credit']}학점{category}")
            if not rag_evidence and not web_evidence:
                lines.append("다만 질문의 최종 판단에 필요한 공식 규정 근거는 현재 연결된 문서에서 확인하지 못했습니다.")
            return "\n".join(lines)
        return "질문을 판단하는 데 필요한 공식 근거를 충분히 확인하지 못했습니다. 과목명, 학기, 인정받으려는 구분을 조금 더 구체적으로 알려주세요."

    def _course_category(self, description: str) -> str | None:
        match = re.search(r"이수구분:\s*([^,\.\n]+)", description)
        return match.group(1).strip() if match else None

    def _contextualize_followup(self, db: Session, student: Student, message: str, current: QueryUnderstanding | None = None) -> str:
        current = current or self._understand_query(message)
        recent_logs = (
            db.query(QueryLog)
            .filter(QueryLog.student_id == student.student_id, QueryLog.route == "reference_rag")
            .order_by(QueryLog.created_at.desc(), QueryLog.id.desc())
            .limit(8)
            .all()
        )
        previous = None
        prior_conditions = []
        for log in recent_logs:
            if self._is_academic_reference_question(log.message):
                previous = log
                break
            if self._is_followup_condition(log.message):
                prior_conditions.append(log.message.strip())
        if previous is None:
            return message
        previous_understanding = self._understand_query(previous.message)
        if not self._should_use_memory(current, previous_understanding):
            return message
        return self._rewrite_followup(previous.message, message, list(reversed(prior_conditions)))

    def _should_use_memory(self, current: QueryUnderstanding, previous: QueryUnderstanding) -> bool:
        if current.explicit_domain and previous.explicit_domain and current.domain != previous.domain:
            return False
        if current.explicit_domain and current.domain != "unknown":
            return current.domain == previous.domain and current.is_followup_candidate
        if current.domain == "unknown":
            return current.is_followup_candidate
        return current.domain == previous.domain and current.is_followup_candidate

    def _looks_like_followup(self, message: str, previous_message: str | None = None) -> bool:
        compact = message.strip().replace(" ", "")
        if not compact:
            return False
        if self._is_followup_condition(message):
            return True
        followup_detail_words = [
            "어디",
            "어디서",
            "어디에",
            "언제",
            "언제까지",
            "몇일까지",
            "서류",
            "뭐필요",
            "뭐가필요",
            "필요해",
            "온라인",
            "방문",
            "접수",
            "신청해",
            "신청하",
            "하면돼",
            "해야돼",
        ]
        if previous_message and len(compact) <= 30 and any(word in compact for word in followup_detail_words):
            return True
        independent_keywords = ["장학", "졸업", "복학", "교환학생", "국제교류", "성적", "수강", "시간표", "등록금", "교수", "강의실", "연락처", "이메일", "축제", "행사"]
        if any(keyword in compact for keyword in independent_keywords):
            return False
        pronoun_followups = ["그건", "그거", "그럼", "그러면", "나는", "저는", "이건", "이거", "그때", "거기"]
        return len(compact) <= 12 and any(word in compact for word in pronoun_followups)

    def _is_followup_condition(self, message: str) -> bool:
        compact = message.strip().replace(" ", "")
        condition_words = [
            "미등록",
            "등록금납부후",
            "등록후",
            "납부후",
            "입대",
            "군휴학",
            "가사",
            "질병",
            "육아",
            "창업",
            "고시",
            "신입생",
            "재학생",
            "편입생",
            "등록전",
            "1학기",
            "2학기",
            "여름계절",
            "겨울계절",
        ]
        return bool(compact) and len(compact) <= 20 and any(word in compact for word in condition_words)

    def _is_academic_reference_question(self, message: str) -> bool:
        keywords = ["휴학", "복학", "장학", "졸업", "신청", "정정", "규정", "교육과정", "전과", "다전공", "출석", "국제교류", "교환학생", "수강"]
        return any(keyword in message for keyword in keywords)

    def _rewrite_followup(self, previous_message: str, message: str, prior_conditions: list[str] | None = None) -> str:
        condition = message.strip()
        condition_prefix = ""
        if prior_conditions:
            condition_prefix = "·".join(prior_conditions[-3:]) + " 조건에서 "
        if "휴학" in previous_message:
            compact = condition.replace(" ", "")
            if "언제" in compact or "기간" in compact or "몇일" in compact or "며칠" in compact:
                return f"{condition_prefix}휴학 신청 기간은 언제까지인가요? 휴학 종류와 등록 여부별 신청 기간을 알려주세요."
            if "서류" in compact or "필요" in compact:
                return f"{condition_prefix}휴학 신청에 필요한 제출서류는 무엇인가요? 휴학 종류별 서류를 알려주세요."
            if "어디" in compact or "접수" in compact:
                return f"{condition_prefix}휴학 신청은 어디서 하나요? 휴학 종류별 온라인 신청 또는 단과대학 행정실 방문 여부를 알려주세요."
            return f"{condition_prefix}{condition} 조건에서 휴학 신청은 어떻게 하나요? 휴학 신청 기간, 신청 방법, 제출서류를 알려주세요."
        if "졸업" in previous_message:
            return f"{condition} 조건에서 졸업 요건을 확인하려면 어떻게 해야 하나요? 이전 질문은 '{previous_message}'입니다."
        if "장학" in previous_message:
            return f"{condition} 조건에서 장학 관련 신청 방법과 주의사항을 알려주세요. 이전 질문은 '{previous_message}'입니다."
        if "수강" in previous_message:
            return f"{condition} 기준으로 수강신청 기간과 수강바구니 일정을 알려주세요. 이전 질문은 '{previous_message}'입니다."
        return f"이전 질문 '{previous_message}'에 이어서, '{condition}' 조건을 반영해 답변해주세요."

    def _answer_from_db(self, db: Session, student: Student, message: str) -> QueryResult | None:
        deterministic = self._answer_from_db_rules(db, student, message)
        if deterministic:
            return deterministic
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

    def _privacy_violation(self, db: Session, student: Student, message: str) -> QueryResult | None:
        private_keywords = ["성적", "학점", "수강", "시간표", "등록금", "개인정보", "정보"]
        if not any(keyword in message for keyword in private_keywords):
            return None
        other_students = db.query(Student.name, Student.student_id).filter(Student.student_id != student.student_id).all()
        for name, student_id in other_students:
            if str(student_id) in message or (name and name in message):
                return QueryResult(
                    route="blocked",
                    answer="다른 학생의 성적, 수강, 등록금 같은 개인정보는 조회할 수 없습니다. 본인 정보만 확인할 수 있어요.",
                    rows=[],
                    sources=[],
                )
        return None

    def _answer_from_db_rules(self, db: Session, student: Student, message: str) -> QueryResult | None:
        if "저번" in message and ("성적" in message or "학점" in message):
            return self._previous_semester_grades(db, student)
        if "학점" in message and any(word in message for word in ["이수", "취득"]):
            return self._earned_credits(db, student)
        if "성적" in message or ("학점" in message and any(word in message for word in ["평점", "성적"])):
            return self._current_grades(db, student)
        if "시간표" in message:
            return self._schedule(db, student, message)
        if "수강" in message or ("내" in message and "과목" in message):
            return self._current_courses(db, student)
        if "등록금" in message:
            return self._tuition(db, student)
        if "선수" in message:
            course_name = self._prerequisite_course_filter(db, message)
            if course_name:
                return self._prerequisite(db, course_name)
            return self._unknown_prerequisite(db, message)
        if self._is_department_professor_list_question(message):
            return self._department_professors(db)
        if ("교수" in message or "교수님" in message) and any(k in message for k in ["이메일", "연구실", "강의실", "수업", "과목"]):
            return self._professor_lookup(db, message)
        if "강의실" in message:
            course_name = self._course_filter(db, message)
            if course_name:
                return self._course_room(db, course_name)
        return None

    def _previous_semester_grades(self, db: Session, student: Student) -> QueryResult:
        semesters = [row[0] for row in db.query(Enrollment.semester).distinct().order_by(Enrollment.semester).all()]
        if len(semesters) < 2:
            return QueryResult(route="db", answer="현재 DB에는 이전 학기 성적 데이터가 없습니다. 저장된 성적 학기는 2026-1뿐입니다.", rows=[], sources=[])
        previous = semesters[-2]
        rows = self.execute_sql(
            db,
            student,
            "SELECT e.semester, c.name AS course_name, e.grade, c.credit "
            "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
            "WHERE e.student_id = :student_id AND e.semester = '" + previous.replace("'", "''") + "' ORDER BY c.name",
        )
        if not rows:
            return QueryResult(route="db", answer=f"{previous} 성적 데이터가 없습니다.", rows=[], sources=[])
        return QueryResult(route="db", answer=self._format_grades(rows, f"{previous} 성적입니다."), rows=rows, sources=[])

    def _current_grades(self, db: Session, student: Student) -> QueryResult:
        rows = self.execute_sql(
            db,
            student,
            "SELECT e.semester, c.name AS course_name, e.grade, c.credit "
            "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
            "WHERE e.student_id = :student_id ORDER BY e.semester DESC, c.name",
        )
        if not rows:
            return QueryResult(route="db", answer="조회 가능한 성적 데이터가 없습니다.", rows=[], sources=[])
        return QueryResult(route="db", answer=self._format_grades(rows, "현재 DB에 저장된 성적입니다."), rows=rows, sources=[])

    def _current_courses(self, db: Session, student: Student) -> QueryResult:
        rows = self.execute_sql(
            db,
            student,
            "SELECT e.semester, c.name AS course_name, c.credit, c.room, p.name AS professor_name "
            "FROM enrollment e JOIN course c ON e.course_id = c.course_id JOIN professor p ON c.professor_id = p.professor_id "
            "WHERE e.student_id = :student_id ORDER BY c.name",
        )
        if not rows:
            return QueryResult(route="db", answer="현재 수강 과목 데이터가 없습니다.", rows=[], sources=[])
        lines = ["현재 DB에 저장된 수강 과목입니다."]
        lines.extend(f"- {row['course_name']} ({row['credit']}학점, {row['professor_name']}, {row['room'].strip()})" for row in rows)
        return QueryResult(route="db", answer="\n".join(lines), rows=rows, sources=[])

    def _earned_credits(self, db: Session, student: Student) -> QueryResult:
        rows = self.execute_sql(
            db,
            student,
            "SELECT e.semester, c.name AS course_name, c.credit, e.grade "
            "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
            "WHERE e.student_id = :student_id ORDER BY e.semester DESC, c.name",
        )
        if not rows:
            return QueryResult(route="db", answer="현재 DB에 이수학점 데이터가 없습니다.", rows=[], sources=[])
        total = sum(int(row["credit"]) for row in rows if row.get("grade") != "F")
        lines = [f"현재 DB 기준 이수/취득으로 계산 가능한 학점은 총 {total}학점입니다."]
        lines.append("동일 과목 재수강, 졸업사정 반영 여부 등은 현재 DB만으로는 확인되지 않습니다.")
        return QueryResult(route="db", answer="\n".join(lines), rows=[{"earned_credits": total}], sources=[])

    def _schedule(self, db: Session, student: Student, message: str) -> QueryResult:
        day = self._day_filter(message)
        if day:
            rows = self.execute_sql(
                db,
                student,
                "SELECT c.name AS course_name, p.name AS professor_name, s.day_of_week, s.start_time, s.end_time, s.room "
                "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
                "JOIN professor p ON c.professor_id = p.professor_id "
                "JOIN schedule s ON c.course_id = s.course_id "
                "WHERE e.student_id = :student_id AND s.day_of_week = '" + day.replace("'", "''") + "' "
                "ORDER BY s.start_time, c.name",
            )
            if not rows:
                label = "오늘" if "오늘" in message else f"{day}요일"
                return QueryResult(route="db", answer=f"{label} 등록된 수업이 없습니다.", rows=[], sources=[])
            label = "오늘" if "오늘" in message else f"{day}요일"
            lines = [f"{label} 시간표입니다."]
            lines.extend(self._format_schedule_lines(rows))
            return QueryResult(route="db", answer="\n".join(lines), rows=rows, sources=[])
        rows = self.execute_sql(
            db,
            student,
            "SELECT c.name AS course_name, p.name AS professor_name, s.day_of_week, s.start_time, s.end_time, s.room "
            "FROM enrollment e JOIN course c ON e.course_id = c.course_id "
            "JOIN professor p ON c.professor_id = p.professor_id "
            "JOIN schedule s ON c.course_id = s.course_id "
            "WHERE e.student_id = :student_id ORDER BY s.day_of_week, s.start_time, c.name",
        )
        if not rows:
            return QueryResult(route="db", answer="현재 DB에 등록된 시간표가 없습니다.", rows=[], sources=[])
        lines = ["현재 DB에 저장된 전체 시간표입니다."]
        lines.extend(self._format_schedule_lines(rows, include_day=True))
        return QueryResult(route="db", answer="\n".join(lines), rows=rows, sources=[])

    def _format_schedule_lines(self, rows: list[dict[str, Any]], include_day: bool = False) -> list[str]:
        grouped: dict[tuple, dict[str, Any]] = {}
        for row in rows:
            key = (
                row.get("day_of_week") if include_day else None,
                row.get("start_time"),
                row.get("end_time"),
                row.get("course_name"),
                (row.get("room") or "").strip(),
            )
            item = grouped.setdefault(key, {**row, "professors": []})
            professor = row.get("professor_name")
            if professor and professor not in item["professors"]:
                item["professors"].append(professor)
        lines = []
        for item in grouped.values():
            day = f"{item['day_of_week']} " if include_day else ""
            professors = ", ".join(item["professors"])
            lines.append(f"- {day}{item['start_time']}-{item['end_time']} {item['course_name']} ({professors}, {(item.get('room') or '').strip()})")
        return lines

    def _tuition(self, db: Session, student: Student) -> QueryResult:
        rows = self.execute_sql(db, student, "SELECT semester, amount, payment_status FROM tuition WHERE student_id = :student_id ORDER BY semester DESC LIMIT 3")
        if not rows:
            return QueryResult(route="db", answer="등록금 데이터가 없습니다.", rows=[], sources=[])
        lines = ["등록금 조회 결과입니다."]
        for row in rows:
            status = "납부 완료" if row["payment_status"] else "미납"
            lines.append(f"- {row['semester']}: {row['amount']:,}원, {status}")
        return QueryResult(route="db", answer="\n".join(lines), rows=rows, sources=[])

    def _department_professors(self, db: Session) -> QueryResult:
        professors = db.query(Professor).order_by(Professor.name).all()
        if not professors:
            return QueryResult(route="db", answer="현재 DB에 등록된 컴퓨터공학부 교수 정보가 없습니다.", rows=[], sources=[])
        lines = ["현재 DB에 등록된 컴퓨터공학부 교수 목록입니다."]
        lines.extend(f"- {professor.name}: {professor.email}, {professor.office}" for professor in professors)
        rows = [{"professor_name": professor.name, "email": professor.email, "office": professor.office} for professor in professors]
        return QueryResult(route="db", answer="\n".join(lines), rows=rows, sources=[])

    def _prerequisite(self, db: Session, course_name: str) -> QueryResult:
        matching_courses = (
            db.query(Course.course_id, Professor.name.label("professor_name"))
            .join(Professor, Course.professor_id == Professor.professor_id)
            .filter(Course.name.contains(course_name))
            .all()
        )
        note_rows = (
            db.query(Course.course_id, Course.name, Professor.name.label("professor_name"), CoursePrerequisiteNote.prerequisites, CoursePrerequisiteNote.note, CoursePrerequisiteNote.source_url)
            .join(CoursePrerequisiteNote, CoursePrerequisiteNote.course_id == Course.course_id)
            .join(Professor, Course.professor_id == Professor.professor_id)
            .filter(Course.name.contains(course_name))
            .order_by(Professor.name, Course.course_id)
            .all()
        )
        if note_rows:
            grouped: dict[tuple[str, str], list[str]] = {}
            sources = []
            for row in note_rows:
                grouped.setdefault((row.professor_name, row.prerequisites), []).append(row.source_url)
                sources.append(row.source_url)
            lines = [f"2026학년도 1학기 공식 강의계획서에서 확인된 {course_name} 선수과목 안내입니다."]
            for (professor_name, prerequisites), _urls in grouped.items():
                lines.append(f"- {professor_name} 교수 분반: {prerequisites}")
            missing_note_count = len({row.course_id for row in matching_courses}) - len({row.course_id for row in note_rows})
            if missing_note_count > 0:
                lines.append(f"- 그 외 {missing_note_count}개 분반은 수강신청 유의사항에서 별도 선수과목 안내가 확인되지 않았습니다.")
            return QueryResult(
                route="db",
                answer="\n".join(lines),
                rows=[{"course_name": course_name, "prerequisites": row.prerequisites, "professor": row.professor_name} for row in note_rows],
                sources=list(dict.fromkeys(sources)),
            )

        TargetCourse = aliased(Course)
        PrereqCourse = aliased(Course)
        target_courses = db.query(TargetCourse).filter(TargetCourse.name.contains(course_name)).all()
        course_ids = [course.course_id for course in target_courses]
        if not course_ids:
            return QueryResult(route="db", answer=f"현재 DB에서 `{course_name}` 과목을 찾지 못했습니다.", rows=[], sources=[])
        if any("2026학년도 1학기" in course.description for course in target_courses):
            sources = []
            for course in target_courses:
                source_id = self._official_section_id(course.description)
                if source_id:
                    sources.append(f"https://kupis.konkuk.ac.kr/sugang/acd/cour/plan/CourLecturePlanInq.jsp?ltShtm=B01011&ltYy=2026&sbjtId={source_id}")
            return QueryResult(
                route="db",
                answer=f"2026학년도 1학기 공식 강의계획서의 수강신청 유의사항에서 {course_name} 선수과목 안내는 확인되지 않습니다.",
                rows=[],
                sources=list(dict.fromkeys(sources)),
            )
        prereq_names = [
            name
            for (name,) in db.query(PrereqCourse.name)
            .select_from(Prerequisite)
            .join(PrereqCourse, Prerequisite.pre_course_id == PrereqCourse.course_id)
            .filter(Prerequisite.course_id.in_(course_ids))
            .distinct()
            .order_by(PrereqCourse.name)
            .all()
        ]
        if not prereq_names:
            return QueryResult(route="db", answer=f"현재 DB 기준으로 {course_name}의 선수과목은 등록되어 있지 않습니다.", rows=[], sources=[])
        names = ", ".join(prereq_names)
        return QueryResult(route="db", answer=f"{course_name} 선수과목은 {names}입니다.", rows=[{"course_name": course_name, "prerequisites": names}], sources=[])

    def _official_section_id(self, description: str) -> str | None:
        match = re.search(r"BBAB\d+-(\d+)", description)
        return match.group(1) if match else None

    def _unknown_prerequisite(self, db: Session, message: str) -> QueryResult:
        subject = self._prerequisite_subject_text(message)
        if not subject or subject in {"프로그래밍", "수업", "과목"}:
            return QueryResult(
                route="db",
                answer="선수과목을 확인할 과목명을 조금 더 구체적으로 입력해주세요. 예: `운영체제 선수과목 알려줘`, `기계학습 선수과목 알려줘`",
                rows=[],
                sources=[],
            )

        mentioned = (
            db.query(Course.name, Professor.name.label("professor_name"), CoursePrerequisiteNote.prerequisites, CoursePrerequisiteNote.source_url)
            .join(CoursePrerequisiteNote, CoursePrerequisiteNote.course_id == Course.course_id)
            .join(Professor, Course.professor_id == Professor.professor_id)
            .filter(CoursePrerequisiteNote.prerequisites.contains(subject))
            .order_by(Course.name, Professor.name)
            .all()
        )
        if mentioned:
            lines = [
                f"현재 2026-1 컴퓨터공학부 개설 과목 DB에서 `{subject}` 과목 자체는 확인되지 않습니다.",
                f"다만 공식 강의계획서에서 `{subject}`이 필요한 선수 지식으로 언급된 과목은 있습니다.",
            ]
            lines.extend(f"- {row.name} ({row.professor_name} 교수 분반): {row.prerequisites}" for row in mentioned[:6])
            return QueryResult(
                route="db",
                answer="\n".join(lines),
                rows=[{"course_name": row.name, "professor": row.professor_name, "prerequisites": row.prerequisites} for row in mentioned],
                sources=list(dict.fromkeys(row.source_url for row in mentioned)),
            )

        return QueryResult(
            route="db",
            answer=f"현재 2026-1 컴퓨터공학부 개설 과목 DB와 공식 강의계획서 note에서 `{subject}`의 선수과목 정보는 확인되지 않습니다.",
            rows=[],
            sources=[],
        )

    def _prerequisite_subject_text(self, message: str) -> str | None:
        before_prereq = message.split("선수", 1)[0].strip()
        before_prereq = re.sub(r"(의|이|가|은|는|을|를|수업|과목)$", "", before_prereq).strip()
        if before_prereq:
            return before_prereq
        return None

    def _professor_lookup(self, db: Session, message: str) -> QueryResult | None:
        professor = self._professor_in_message(db, message)
        if professor is None:
            return None
        courses = (
            db.query(Course.name, Course.room)
            .filter(Course.professor_id == professor.professor_id)
            .order_by(Course.name)
            .all()
        )
        if "강의실" in message or "수업" in message or "과목" in message:
            course_filter = self._course_filter(db, message)
            if course_filter:
                matched = [(name, room) for name, room in courses if course_filter in name]
                if matched:
                    lines = [f"{professor.name} 교수님의 {matched[0][0]} 강의실은 {matched[0][1].strip()}입니다."]
                    lines.extend(f"- {name}: {room.strip()}" for name, room in matched[1:])
                    return QueryResult(route="db", answer="\n".join(lines), rows=[{"course_name": n, "room": r} for n, r in matched], sources=[])
                owners = (
                    db.query(Course.name, Course.room, Professor.name.label("professor_name"))
                    .join(Professor)
                    .filter(Course.name.contains(course_filter))
                    .order_by(Course.name)
                    .all()
                )
                if owners:
                    owner_text = ", ".join(f"{name}({professor_name}, {room.strip()})" for name, room, professor_name in owners)
                    return QueryResult(
                        route="db",
                        answer=f"현재 DB 기준으로 `{course_filter}` 과목은 {professor.name} 교수님의 등록 과목이 아닙니다. 확인된 과목 정보는 {owner_text}입니다.",
                        rows=[{"course_name": n, "room": r, "professor_name": p} for n, r, p in owners],
                        sources=[],
                    )
                current = ", ".join(f"{name}({room.strip()})" for name, room in courses) or "등록 과목 없음"
                return QueryResult(
                    route="db",
                    answer=f"현재 DB에서 {professor.name} 교수님의 `{course_filter}` 과목은 확인되지 않습니다. 등록된 과목은 {current}입니다.",
                    rows=[{"course_name": n, "room": r} for n, r in courses],
                    sources=[],
                )
            lines = [f"{professor.name} 교수님의 현재 DB 등록 과목입니다."]
            lines.extend(f"- {name}: {room.strip()}" for name, room in courses)
            return QueryResult(route="db", answer="\n".join(lines), rows=[{"course_name": n, "room": r} for n, r in courses], sources=[])
        answer = f"{professor.name} 교수님 이메일은 {professor.email}, 연구실은 {professor.office}입니다."
        return QueryResult(route="db", answer=answer, rows=[{"professor_name": professor.name, "email": professor.email, "office": professor.office}], sources=[])

    def _course_room(self, db: Session, course_name: str) -> QueryResult:
        rows = (
            db.query(Course.name, Course.room, Professor.name.label("professor_name"))
            .join(Professor)
            .filter(Course.name.contains(course_name))
            .order_by(Course.name)
            .all()
        )
        if not rows:
            return QueryResult(route="db", answer=f"현재 DB에서 `{course_name}` 과목은 확인되지 않습니다.", rows=[], sources=[])
        lines = [f"`{course_name}` 관련 강의실입니다."]
        lines.extend(f"- {name} ({professor_name}): {room.strip()}" for name, room, professor_name in rows)
        return QueryResult(route="db", answer="\n".join(lines), rows=[{"course_name": n, "room": r, "professor_name": p} for n, r, p in rows], sources=[])

    def _format_grades(self, rows: list[dict[str, Any]], title: str) -> str:
        lines = [title]
        lines.extend(f"- {row['semester']} {row['course_name']}: {row['grade']} ({row['credit']}학점)" for row in rows)
        return "\n".join(lines)

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
        course_filter = self._course_filter(None, message)
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
            if not course_filter:
                return None
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

    def _course_filter(self, db: Session | None, message: str) -> str | None:
        return self._course_filter_from_text(db, message)

    def _prerequisite_course_filter(self, db: Session | None, message: str) -> str | None:
        if "선수" in message:
            before_prereq = message.split("선수", 1)[0]
            course_name = self._course_filter_from_text(db, before_prereq)
            if course_name:
                return course_name
        return self._course_filter_from_text(db, message)

    def _course_filter_from_text(self, db: Session | None, text: str) -> str | None:
        known = []
        if db is not None:
            known.extend(name for (name,) in db.query(Course.name).all())
        known.extend([
            "컴공개",
            "데이터베이스",
            "운영체제",
            "자료구조",
            "알고리즘",
            "컴퓨터네트워크",
            "소프트웨어공학",
            "인공지능",
            "기계학습",
            "자연어처리",
            "웹프로그래밍",
            "모바일프로그래밍",
            "컴퓨터구조",
            "임베디드시스템소프트웨어",
            "캡스톤디자인",
            "정보보호",
            "졸업프로젝트2",
            "졸업프로젝트1",
        ])
        for name in sorted(set(known), key=len, reverse=True):
            if name in text:
                return name
        return None

    def _course_aliases(self) -> list[str]:
        return [
            "C프로그래밍",
            "C++프로그래밍",
            "C++Programming",
            "Python",
            "파이썬",
            "JAVA프로그래밍",
            "자바프로그래밍",
        ]

    def _day_filter(self, message: str) -> str | None:
        if "오늘" in message:
            return ["월", "화", "수", "목", "금", "토", "일"][datetime.now(ZoneInfo("Asia/Seoul")).weekday()]
        day_words = {
            "월요일": "월",
            "월욜": "월",
            "화요일": "화",
            "화욜": "화",
            "수요일": "수",
            "수욜": "수",
            "목요일": "목",
            "목욜": "목",
            "금요일": "금",
            "금욜": "금",
            "토요일": "토",
            "토욜": "토",
            "일요일": "일",
            "일욜": "일",
        }
        for word, day in day_words.items():
            if word in message:
                return day
        return None

    def _professor_in_message(self, db: Session, message: str) -> Professor | None:
        professors = db.query(Professor).all()
        for professor in professors:
            if professor.name in message:
                return professor
        return None

    def _summarize_rows(self, message: str, rows: list[dict[str, Any]]) -> str:
        compact = [self._public_row(row) for row in rows[:8]]
        instructions = (
            "DB 조회 결과를 한국어로 짧고 자연스럽게 답하세요. "
            "Markdown 강조 문법(**, __)과 제목, 표를 사용하지 마세요. "
            "사용자에게 내부 DB 컬럼명, SQL, id 값은 말하지 마세요. "
            "값이 명확하면 한두 문장으로 답하세요. "
            "숫자 금액은 쉼표를 넣어 표현하세요. "
            "없는 정보는 꾸며내지 마세요."
        )
        llm = openai_service.complete_text(instructions, f"질문: {message}\n결과: {compact}")
        if llm:
            return self._clean_llm_db_answer(llm)
        parts = []
        for row in compact:
            parts.append(", ".join(f"{k}: {v}" for k, v in row.items()))
        suffix = f" 외 {len(rows) - len(compact)}건" if len(rows) > len(compact) else ""
        return "조회 결과입니다. " + " / ".join(parts) + suffix

    def _clean_llm_db_answer(self, answer: str) -> str:
        return answer.replace("**", "").replace("__", "").strip()

    def _public_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if not key.endswith("_id") and key != "id"}

    def _log(self, db: Session, student_id: int, message: str, route: str, sql: str | None, success: bool, error: str | None) -> None:
        db.add(QueryLog(student_id=student_id, message=message, route=route, generated_sql=sql, success=success, error=error))
        db.commit()


query_service = QueryService()
