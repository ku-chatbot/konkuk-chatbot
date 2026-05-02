from app.services.result_summarizer import ResultSummarizer


def test_multiple_rows_returns_table_format():
    rows = [
        {"course_name": "데이터베이스", "grade": "A+"},
        {"course_name": "자료구조", "grade": "B+"},
    ]
    result = ResultSummarizer().summarize("내 성적 보여줘", rows)
    assert result.display_format == "table"
    assert "2건" in result.answer


def test_single_row_returns_summary_format():
    rows = [{"semester": "2026-1", "amount": 4_100_000, "payment_status": True}]
    result = ResultSummarizer().summarize("등록금 얼마야?", rows)
    assert result.display_format == "summary"
    # LLM is None (no API key) so it falls back to dict serialization
    assert result.answer  # non-empty


def test_empty_rows_returns_summary_format():
    result = ResultSummarizer().summarize("내 정보", [])
    assert result.display_format == "summary"
    assert result.answer == "조회 결과가 없습니다."


def test_headline_includes_row_count():
    rows = [{"x": i} for i in range(7)]
    result = ResultSummarizer().summarize("질문", rows)
    assert result.display_format == "table"
    assert "7건" in result.answer
