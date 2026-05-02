import pytest

from app.services.sql_guard import validate_select_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM enrollment WHERE student_id = :student_id",
        "SELECT * FROM tuition WHERE student_id = :student_id",
        "SELECT student_id, name FROM student WHERE student_id = :student_id",
        "SELECT name FROM course",
        "SELECT name FROM professor",
        "SELECT name FROM course WHERE name LIKE :course_pattern",
        "SELECT c.name, p.email FROM course c JOIN professor p ON c.professor_id = p.professor_id",
        (
            "SELECT e.semester, c.name AS course_name, e.grade FROM enrollment e "
            "JOIN course c ON e.course_id = c.course_id "
            "WHERE e.student_id = :student_id ORDER BY e.semester"
        ),
    ],
)
def test_allowed_select_passes(sql):
    ok, reason = validate_select_sql(sql)
    assert ok, f"expected pass but got: {reason}"


@pytest.mark.parametrize(
    "sql, expected_substr",
    [
        ("DROP TABLE student", "SELECT"),
        ("INSERT INTO student VALUES (1)", "SELECT"),
        ("UPDATE student SET name='x'", "SELECT"),
        ("SELECT * FROM enrollment; DROP TABLE student", "하나의 SQL"),
        ("SELECT * FROM secret_table", "허용되지 않은"),
        ("SELECT * FROM student", "student_id"),
        ("SELECT * FROM enrollment", "student_id"),
        ("SELECT * FROM tuition", "student_id"),
        ("SELECT * FROM enrollment WHERE student_id = 202214001", "리터럴"),
        ("SELECT * FROM enrollment WHERE student_id IN (1, 2)", "student_id"),
        ("SELECT student_id FROM enrollment", "student_id"),
        ("SELECT * FROM student WHERE student_id != 202214001", "리터럴"),
    ],
)
def test_blocked_select_rejected(sql, expected_substr):
    ok, reason = validate_select_sql(sql)
    assert not ok
    assert expected_substr in reason


def test_blocks_pragma_keyword():
    ok, reason = validate_select_sql("SELECT * FROM student WHERE student_id = :student_id PRAGMA foreign_keys")
    assert not ok
    assert "PRAGMA" in reason
