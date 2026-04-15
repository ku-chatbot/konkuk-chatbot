from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Student
from app.routers.deps import get_current_student
from app.services.query_service import query_service

router = APIRouter(prefix="/mcp", tags=["mcp"])


class SQLRequest(BaseModel):
    sql: str


@router.get("/schema")
def schema() -> dict:
    return query_service.schema()


@router.post("/query")
def query(payload: SQLRequest, db: Session = Depends(get_db), current_student: Student = Depends(get_current_student)) -> dict:
    try:
        rows = query_service.execute_sql(db, current_student, payload.sql)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rows": rows}
