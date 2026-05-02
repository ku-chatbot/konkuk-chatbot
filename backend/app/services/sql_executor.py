from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Student
from app.services.sql_guard import validate_select_sql


class SqlExecutor:
    def execute(
        self,
        db: Session,
        student: Student,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ok, reason = validate_select_sql(sql)
        if not ok:
            raise ValueError(reason)
        bind_params = {**(params or {}), "student_id": student.student_id}
        return [dict(row._mapping) for row in db.execute(text(sql), bind_params).fetchall()]


sql_executor = SqlExecutor()
