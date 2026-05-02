import pytest

from app.services.sql_executor import SqlExecutor


@pytest.fixture
def executor() -> SqlExecutor:
    return SqlExecutor()


def test_executor_injects_student_id(db, student, executor):
    rows = executor.execute(
        db,
        student,
        "SELECT semester, amount, payment_status FROM tuition WHERE student_id = :student_id",
    )
    assert len(rows) == 1
    assert rows[0]["amount"] == 4_100_000


def test_executor_overrides_caller_supplied_student_id(db, student, executor):
    """SqlExecutor must always overwrite student_id with the authenticated student."""
    rows = executor.execute(
        db,
        student,
        "SELECT amount FROM tuition WHERE student_id = :student_id",
        params={"student_id": 202214002},  # attempted impersonation
    )
    # Result must reflect the authenticated student (202214001), not the spoofed id.
    assert len(rows) == 1
    assert rows[0]["amount"] == 4_100_000


def test_executor_passes_named_params(db, student, executor):
    rows = executor.execute(
        db,
        student,
        "SELECT name FROM course WHERE name LIKE :course_pattern ORDER BY name",
        params={"course_pattern": "%데이터%"},
    )
    assert any("데이터베이스" in row["name"] for row in rows)


def test_executor_rejects_disallowed_sql(db, student, executor):
    with pytest.raises(ValueError):
        executor.execute(db, student, "DROP TABLE student")


def test_executor_rejects_literal_student_id(db, student, executor):
    with pytest.raises(ValueError):
        executor.execute(db, student, "SELECT * FROM enrollment WHERE student_id = 202214002")


def test_executor_does_not_leak_other_student_grades(db, student, executor):
    rows = executor.execute(
        db,
        student,
        "SELECT e.semester, c.name, e.grade FROM enrollment e "
        "JOIN course c ON e.course_id = c.course_id "
        "WHERE e.student_id = :student_id",
    )
    course_names = {row["name"] for row in rows}
    # Student 1 is enrolled in 데이터베이스/자료구조/알고리즘 — never 운영체제 (which belongs to student 2).
    assert "운영체제" not in course_names
