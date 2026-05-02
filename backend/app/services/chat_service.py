from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models import QueryLog, Student
from app.services.query_router import GeneralAnswerService, QueryRouter, general_answer_service, query_router
from app.services.reference_rag_service import reference_rag_service
from app.services.result_summarizer import ResultSummarizer, result_summarizer
from app.services.sql_executor import SqlExecutor, sql_executor
from app.services.sql_guard import validate_select_sql
from app.services.text_to_sql import GeneratedSql, TextToSQLService, text_to_sql_service


@dataclass
class ChatResult:
    route: str
    answer: str
    display_format: str = "summary"
    sql: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class DbAttempt:
    """Outcome of attempting to answer from the DB. Used both as the return value
    of _answer_from_db and as the source of QueryLog metadata."""

    result: ChatResult | None
    sql: str | None
    errors: list[str] = field(default_factory=list)

    @property
    def has_answer(self) -> bool:
        return self.result is not None and self.result.rows != []

    @property
    def is_empty_result(self) -> bool:
        return self.result is not None and self.result.rows == []


class ChatService:
    def __init__(
        self,
        router: QueryRouter = query_router,
        general: GeneralAnswerService = general_answer_service,
        text_to_sql: TextToSQLService = text_to_sql_service,
        executor: SqlExecutor = sql_executor,
        summarizer: ResultSummarizer = result_summarizer,
    ) -> None:
        self.router = router
        self.general = general
        self.text_to_sql = text_to_sql
        self.executor = executor
        self.summarizer = summarizer

    def answer(self, db: Session, student: Student, message: str) -> ChatResult:
        general = self.general.try_answer(message)
        if general:
            self._log(db, student.student_id, message, route="general", sql=None, success=True, error=None)
            return ChatResult(route="general", answer=general.answer)

        route = self.router.classify(db, message)
        attempt: DbAttempt | None = None
        if route == "db":
            attempt = self._answer_from_db(db, student, message)
            if attempt.has_answer:
                self._log(
                    db,
                    student.student_id,
                    message,
                    route="db",
                    sql=attempt.sql,
                    success=True,
                    error="; ".join(attempt.errors) or None,
                )
                return attempt.result
            if attempt.is_empty_result:
                self._log(
                    db,
                    student.student_id,
                    message,
                    route="db_no_result",
                    sql=attempt.sql,
                    success=False,
                    error="; ".join(attempt.errors) or "no_rows",
                )
                return attempt.result

        rag = reference_rag_service.answer(db, message)
        rag_route = rag.route if attempt is None else f"{rag.route}_after_db_failed"
        rag_success = bool(rag.sources)
        rag_error = "; ".join(attempt.errors) if attempt and attempt.errors else (
            None if rag_success else "rag_no_sources"
        )
        self._log(
            db,
            student.student_id,
            message,
            route=rag_route,
            sql=attempt.sql if attempt else None,
            success=rag_success,
            error=rag_error,
        )
        return ChatResult(route=rag.route, answer=rag.answer, sources=rag.sources)

    def _answer_from_db(self, db: Session, student: Student, message: str) -> DbAttempt:
        llm_candidate = self.text_to_sql.generate_with_llm(message)
        rule_candidate = self.text_to_sql.generate_with_rules(message)
        candidates: list[tuple[str, GeneratedSql]] = []
        if llm_candidate is not None:
            candidates.append(("llm", llm_candidate))
        else:
            # No LLM SQL produced (key missing or LLM said unanswerable).
            # Not strictly an error, but worth logging when no rule candidate exists either.
            pass
        if rule_candidate is not None:
            candidates.append(("rule", rule_candidate))

        errors: list[str] = []
        last_executed: GeneratedSql | None = None
        for source, candidate in candidates:
            if not validate_select_sql(candidate.sql)[0]:
                errors.append(f"{source}_sql_rejected_by_guard")
                continue
            try:
                rows = self.executor.execute(db, student, candidate.sql, candidate.params)
            except Exception as exc:
                errors.append(f"{source}_sql_execution_error: {exc}")
                continue
            last_executed = candidate
            if rows:
                summary = self.summarizer.summarize(message, rows)
                result = ChatResult(
                    route="db",
                    answer=summary.answer,
                    display_format=summary.display_format,
                    sql=candidate.sql,
                    rows=rows,
                )
                return DbAttempt(result=result, sql=candidate.sql, errors=errors)
            errors.append(f"{source}_sql_no_rows")

        if last_executed is not None:
            result = ChatResult(
                route="db",
                answer="조회 결과가 없습니다. 질문의 과목명이나 학기를 조금 더 구체적으로 적어주세요.",
                sql=last_executed.sql,
            )
            return DbAttempt(result=result, sql=last_executed.sql, errors=errors)

        if not candidates:
            errors.append("no_sql_candidates_generated")
        return DbAttempt(result=None, sql=None, errors=errors)

    def _log(
        self,
        db: Session,
        student_id: int,
        message: str,
        *,
        route: str,
        sql: str | None,
        success: bool,
        error: str | None,
    ) -> None:
        db.add(
            QueryLog(
                student_id=student_id,
                message=message,
                route=route,
                generated_sql=sql,
                success=success,
                error=error,
            )
        )
        db.commit()


chat_service = ChatService()
