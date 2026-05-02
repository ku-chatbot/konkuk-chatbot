import re


ALLOWED_TABLES = {"student", "professor", "course", "enrollment", "schedule", "tuition", "prerequisite"}
BLOCKED_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "replace",
    "truncate",
    "attach",
    "detach",
    "pragma",
}
STUDENT_SCOPED_TABLES = {"student", "enrollment", "tuition"}

_LITERAL_STUDENT_ID = re.compile(r"student_id\s*(?:=|in|<|>|!=|<=|>=)\s*\d")
_BIND_STUDENT_ID = re.compile(r"student_id\s*=\s*:student_id\b")


def validate_select_sql(sql: str) -> tuple[bool, str | None]:
    normalized = " ".join(sql.strip().split()).lower()
    if not normalized.startswith("select "):
        return False, "SELECT 조회 쿼리만 실행할 수 있습니다."
    if ";" in normalized.rstrip(";"):
        return False, "한 번에 하나의 SQL만 실행할 수 있습니다."
    for keyword in BLOCKED_KEYWORDS:
        if re.search(rf"\b{keyword}\b", normalized):
            return False, f"{keyword.upper()} 문은 허용되지 않습니다."
    referenced_tables = set(re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", normalized))
    unknown = referenced_tables - ALLOWED_TABLES
    if unknown:
        return False, f"허용되지 않은 테이블입니다: {', '.join(sorted(unknown))}"
    if _LITERAL_STUDENT_ID.search(normalized):
        return False, "학번 리터럴은 허용되지 않습니다. :student_id 바인딩만 사용하세요."
    if referenced_tables & STUDENT_SCOPED_TABLES and not _BIND_STUDENT_ID.search(normalized):
        return False, "학생 정보 조회에는 student_id = :student_id 바인딩이 필요합니다."
    return True, None
