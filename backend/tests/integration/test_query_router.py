import pytest

from app.services.query_router import QueryRouter


@pytest.fixture
def router() -> QueryRouter:
    return QueryRouter()


def test_course_name_plus_db_keyword_routes_to_db(db, router):
    assert router.classify(db, "데이터베이스 교수 이메일 알려줘") == "db"


def test_personal_keyword_routes_to_db(db, router):
    assert router.classify(db, "내 성적 보여줘") == "db"


def test_tuition_keyword_routes_to_db(db, router):
    assert router.classify(db, "이번 학기 등록금 얼마야?") == "db"


def test_reference_keyword_routes_to_rag(db, router):
    assert router.classify(db, "휴학 신청은 어떻게 해?") == "reference_rag"


def test_personal_with_reference_keyword_routes_to_rag(db, router):
    """After A-fix: '내' should not block reference routing for '내 휴학'."""
    assert router.classify(db, "내 휴학 어떻게 신청해?") == "reference_rag"


def test_graduation_question_routes_to_rag(db, router):
    assert router.classify(db, "졸업 요건 알려줘") == "reference_rag"


def test_scholarship_question_routes_to_rag(db, router):
    assert router.classify(db, "장학금 종류 알려줘") == "reference_rag"


def test_professor_keyword_alone_no_longer_forces_db(db, router):
    """After A-fix: '교수' alone is no longer in DB_KEYWORDS, so generic
    professor questions fall through to default RAG."""
    assert router.classify(db, "교수 임용 절차 알려줘") == "reference_rag"


def test_unknown_topic_defaults_to_rag(db, router):
    assert router.classify(db, "도서관 운영 시간 알려줘") == "reference_rag"


def test_schedule_routes_to_db(db, router):
    assert router.classify(db, "내 시간표 알려줘") == "db"


def test_prerequisite_routes_to_db(db, router):
    assert router.classify(db, "내 선수과목 알려줘") == "db"
