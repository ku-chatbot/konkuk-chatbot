from datetime import datetime

from freezegun import freeze_time

from app.services.query_router import GeneralAnswerService


# 2026-05-02 14:30 KST == 2026-05-02 05:30 UTC. Freeze in UTC so that
# datetime.now(ZoneInfo("Asia/Seoul")) inside the service yields the KST instant.
@freeze_time("2026-05-02 05:30:00")
def test_date_question_returns_today():
    service = GeneralAnswerService()
    result = service.try_answer("오늘 며칠이야?")
    assert result is not None
    assert "2026년" in result.answer
    assert "5월" in result.answer
    assert "2일" in result.answer
    assert "토" in result.answer  # 2026-05-02 is Saturday


@freeze_time("2026-05-02 05:30:00")
def test_time_question_returns_now():
    service = GeneralAnswerService()
    result = service.try_answer("지금 몇시야?")
    assert result is not None
    assert "14:30" in result.answer


def test_unrelated_message_returns_none():
    service = GeneralAnswerService()
    assert service.try_answer("내 성적 보여줘") is None


def test_date_question_with_spaces():
    # "지금 몇 일" should still match because compact removes spaces
    service = GeneralAnswerService()
    result = service.try_answer("지금   몇  일")
    assert result is not None


def test_real_now_smoke():
    """Smoke test without freezegun to confirm zoneinfo path works."""
    service = GeneralAnswerService()
    result = service.try_answer("오늘 날짜 알려")
    assert result is not None
    # answer must contain the current year
    assert str(datetime.now().year) in result.answer
