from dataclasses import dataclass

import pytest

from app.services import chat_service as chat_service_module
from app.services import reference_rag_service as reference_rag_module
from app.services import result_summarizer as summarizer_module
from app.services import text_to_sql as text_to_sql_module
from app.services.chat_service import ChatService


@dataclass
class FakeRagAnswer:
    route: str = "reference_rag"
    answer: str = "RAG 답변입니다."
    sources: list[str] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = ["참고문서, p.1 - https://example.com"]


@pytest.fixture
def fake_rag(monkeypatch):
    def _answer(_db, _message, top_k=5):
        return FakeRagAnswer()

    monkeypatch.setattr(reference_rag_module.reference_rag_service, "answer", _answer)


def test_general_question_short_circuits(db, student, fake_rag):
    service = ChatService()
    result = service.answer(db, student, "오늘 며칠이야?")
    assert result.route == "general"
    assert "년" in result.answer


def test_db_route_uses_fallback_when_llm_disabled(db, student, fake_rag):
    """No OPENAI_API_KEY → LLM SQL is None → fallback rule kicks in for tuition."""
    service = ChatService()
    result = service.answer(db, student, "이번 학기 등록금 얼마야?")
    assert result.route == "db"
    assert result.sql is not None
    assert len(result.rows) == 1
    assert result.rows[0]["amount"] == 4_100_000


def test_db_route_returns_table_format_for_multi_rows(db, student, fake_rag):
    service = ChatService()
    result = service.answer(db, student, "내 성적 보여줘")
    assert result.route == "db"
    assert result.display_format == "table"
    assert len(result.rows) >= 2


def test_db_route_returns_summary_format_for_single_row(db, student, fake_rag):
    service = ChatService()
    result = service.answer(db, student, "내 정보 알려줘")
    assert result.route == "db"
    assert result.display_format == "summary"
    assert len(result.rows) == 1


def test_unmatched_message_falls_back_to_rag(db, student, fake_rag):
    service = ChatService()
    result = service.answer(db, student, "도서관 위치 어디야?")
    assert result.route == "reference_rag"
    assert result.answer == "RAG 답변입니다."
    assert result.sources


def test_llm_invalid_sql_falls_back_to_rule(db, student, monkeypatch, fake_rag):
    """Simulate LLM returning a SQL that violates sql_guard; rule fallback should still answer."""

    def fake_generate_with_llm(_self, _message):
        from app.services.text_to_sql import GeneratedSql

        # Literal student_id → guard rejects it.
        return GeneratedSql(
            sql="SELECT amount FROM tuition WHERE student_id = 202214002",
            params={},
        )

    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_llm", fake_generate_with_llm)
    service = ChatService()
    result = service.answer(db, student, "이번 학기 등록금 얼마야?")
    assert result.route == "db"
    # The rule fallback returns the authenticated student's tuition, not the spoofed one.
    assert result.rows[0]["amount"] == 4_100_000


def test_db_no_rows_returns_friendly_message(db, student, monkeypatch, fake_rag):
    """If both LLM and rule produce SQL but execution returns no rows, ChatService
    must return the 'no result' message instead of falling all the way to RAG."""

    def fake_generate_with_rules(_self, message):
        from app.services.text_to_sql import GeneratedSql

        # SQL that runs successfully but returns no rows for student 202214001
        # (no tuition row for an unrealistic semester).
        return GeneratedSql(
            sql="SELECT amount FROM tuition WHERE student_id = :student_id AND semester = '1900-1'",
            params={},
        )

    def no_llm(_self, _message):
        return None

    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_llm", no_llm)
    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_rules", fake_generate_with_rules)
    service = ChatService()
    result = service.answer(db, student, "이번 학기 등록금 얼마야?")
    assert result.route == "db"
    assert "조회 결과가 없습니다" in result.answer
    assert result.rows == []


def test_summarizer_receives_rows_via_llm_mock(db, student, monkeypatch, fake_rag):
    """When LLM is available, single-row summary path should use it."""

    monkeypatch.setattr(
        summarizer_module.openai_service,
        "complete_text",
        lambda _instructions, _user_input: "이번 학기 등록금은 4,100,000원이고 납부 완료되었습니다.",
    )
    service = ChatService()
    result = service.answer(db, student, "이번 학기 등록금 얼마야?")
    assert result.display_format == "summary"
    assert "4,100,000" in result.answer


# ----- QueryLog assertions -----

from app.models import QueryLog  # noqa: E402


def _last_log(db, student) -> QueryLog:
    return (
        db.query(QueryLog)
        .filter(QueryLog.student_id == student.student_id)
        .order_by(QueryLog.id.desc())
        .first()
    )


def test_log_records_general_route_as_success(db, student):
    ChatService().answer(db, student, "오늘 며칠이야?")
    log = _last_log(db, student)
    assert log.route == "general"
    assert log.success is True
    assert log.error is None
    assert log.generated_sql is None


def test_log_records_db_route_with_sql(db, student):
    ChatService().answer(db, student, "이번 학기 등록금 얼마야?")
    log = _last_log(db, student)
    assert log.route == "db"
    assert log.success is True
    assert log.generated_sql is not None
    assert "tuition" in log.generated_sql.lower()


def test_log_records_llm_guard_rejection_in_error_field(db, student, monkeypatch):
    def fake_llm(_self, _message):
        from app.services.text_to_sql import GeneratedSql

        return GeneratedSql(sql="SELECT amount FROM tuition WHERE student_id = 202214002", params={})

    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_llm", fake_llm)
    ChatService().answer(db, student, "이번 학기 등록금 얼마야?")
    log = _last_log(db, student)
    assert log.route == "db"
    assert log.success is True  # rule fallback succeeded
    assert log.error is not None
    assert "llm_sql_rejected_by_guard" in log.error


def test_log_records_db_no_result_as_failure(db, student, monkeypatch):
    def fake_rule(_self, _message):
        from app.services.text_to_sql import GeneratedSql

        return GeneratedSql(
            sql="SELECT amount FROM tuition WHERE student_id = :student_id AND semester = '1900-1'",
            params={},
        )

    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_llm", lambda *a, **kw: None)
    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_rules", fake_rule)
    ChatService().answer(db, student, "이번 학기 등록금 얼마야?")
    log = _last_log(db, student)
    assert log.route == "db_no_result"
    assert log.success is False
    assert log.error is not None
    assert "no_rows" in log.error or "rule_sql_no_rows" in log.error


def test_log_records_rag_after_db_failed_when_db_has_no_candidates(db, student, monkeypatch, fake_rag):
    """If DB route is chosen but neither LLM nor rule yields a candidate, the RAG
    fallback log should mark the route as reference_rag_after_db_failed."""
    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_llm", lambda *a, **kw: None)
    monkeypatch.setattr(text_to_sql_module.TextToSQLService, "generate_with_rules", lambda *a, **kw: None)
    # "내 강의실" → DB keyword "내" + "강의실" routes to db, but no rule matches the
    # exact phrasing that the fallback expects after we strip generate_with_rules.
    ChatService().answer(db, student, "내 강의실")
    log = _last_log(db, student)
    assert log.route == "reference_rag_after_db_failed"
    assert log.error is not None


def test_log_records_pure_rag_route_when_router_chooses_rag(db, student, fake_rag):
    ChatService().answer(db, student, "휴학 신청은 어떻게 해?")
    log = _last_log(db, student)
    # RAG was the first choice, not a fallback after DB failure.
    assert log.route == "reference_rag"
