from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Student
from app.routers.deps import get_current_student
from app.services.sql_executor import sql_executor

router = APIRouter(prefix="/mcp", tags=["mcp"])


SCHEMA = {
    "tables": {
        "student": ["student_id", "name", "major", "admission_year", "status"],
        "professor": ["professor_id", "name", "email", "office"],
        "course": ["course_id", "name", "credit", "room", "description", "professor_id"],
        "enrollment": ["enrollment_id", "semester", "grade", "student_id", "course_id"],
        "schedule": ["schedule_id", "day_of_week", "start_time", "end_time", "room", "course_id"],
        "tuition": ["tuition_id", "semester", "amount", "payment_status", "student_id"],
        "prerequisite": ["id", "course_id", "pre_course_id"],
    }
}


class SQLRequest(BaseModel):
    sql: str


@router.get("/schema")
def schema() -> dict:
    return SCHEMA


@router.post("/query")
def query(payload: SQLRequest, db: Session = Depends(get_db), current_student: Student = Depends(get_current_student)) -> dict:
    try:
        rows = sql_executor.execute(db, current_student, payload.sql)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rows": rows}
