import pytest

from app.services.text_to_sql import KNOWN_COURSE_NAMES, TextToSQLService


@pytest.fixture
def service() -> TextToSQLService:
    return TextToSQLService()


def test_fallback_for_tuition(service):
    generated = service.generate_with_rules("이번 학기 등록금 얼마야?")
    assert generated is not None
    assert "tuition" in generated.sql.lower()
    assert "student_id = :student_id" in generated.sql
    assert generated.params == {}


def test_fallback_for_grade(service):
    generated = service.generate_with_rules("내 성적 보여줘")
    assert generated is not None
    assert "enrollment" in generated.sql.lower()
    assert "grade" in generated.sql.lower()
    assert "student_id = :student_id" in generated.sql


def test_fallback_for_credit_synonym(service):
    generated = service.generate_with_rules("이번 학기 학점 알려줘")
    assert generated is not None
    assert "grade" in generated.sql.lower()


def test_fallback_for_schedule(service):
    generated = service.generate_with_rules("내 시간표 알려줘")
    assert generated is not None
    assert "schedule" in generated.sql.lower()
    assert "day_of_week" in generated.sql


def test_fallback_for_professor_with_course_filter(service):
    generated = service.generate_with_rules("데이터베이스 교수 이메일 알려줘")
    assert generated is not None
    assert "professor" in generated.sql.lower()
    assert "course_pattern" in generated.params
    assert generated.params["course_pattern"] == "%데이터베이스%"


def test_fallback_for_professor_without_course_filter(service):
    generated = service.generate_with_rules("내 수업 교수 이메일 알려줘")
    assert generated is not None
    assert "professor" in generated.sql.lower()
    assert "student_id = :student_id" in generated.sql
    assert generated.params == {}


def test_fallback_for_prerequisite_with_course_filter(service):
    generated = service.generate_with_rules("알고리즘 선수과목 알려줘")
    assert generated is not None
    assert "prerequisite" in generated.sql.lower()
    assert generated.params["course_pattern"] == "%알고리즘%"


def test_fallback_for_prerequisite_without_course_filter(service):
    generated = service.generate_with_rules("선수과목 목록 보여줘")
    assert generated is not None
    assert "prerequisite" in generated.sql.lower()
    assert generated.params == {}


def test_fallback_for_my_info(service):
    generated = service.generate_with_rules("내 정보 알려줘")
    assert generated is not None
    assert "student" in generated.sql.lower()
    assert "student_id = :student_id" in generated.sql


def test_fallback_for_courses(service):
    generated = service.generate_with_rules("내 수강 과목 알려줘")
    assert generated is not None
    assert "enrollment" in generated.sql.lower()


def test_fallback_returns_none_for_unknown(service):
    assert service.generate_with_rules("오늘 날씨 어때?") is None


def test_course_filter_recognizes_known_names(service):
    for name in KNOWN_COURSE_NAMES:
        assert service._course_filter(f"{name} 수업 알려줘") == name


def test_course_filter_returns_none_for_unknown(service):
    assert service._course_filter("개론 수업 알려줘") is None


def test_generate_with_llm_returns_none_when_no_api_key(service):
    # OPENAI_API_KEY is forced empty in conftest, so openai_service returns None.
    assert service.generate_with_llm("내 성적 보여줘") is None
