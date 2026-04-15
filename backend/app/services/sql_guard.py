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
    if "student_id" not in normalized and "student" in referenced_tables:
        return False, "학생 정보 조회에는 student_id 제한이 필요합니다."
    if "enrollment" in referenced_tables and "student_id" not in normalized:
        return False, "수강 정보 조회에는 student_id 제한이 필요합니다."
    if "tuition" in referenced_tables and "student_id" not in normalized:
        return False, "등록금 조회에는 student_id 제한이 필요합니다."
    return True, None
