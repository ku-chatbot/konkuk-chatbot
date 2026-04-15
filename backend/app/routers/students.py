from fastapi import APIRouter, Depends

from app.models import Student
from app.routers.deps import get_current_student
from app.schemas.auth import StudentMe

router = APIRouter(prefix="/students", tags=["students"])


@router.get("/me", response_model=StudentMe)
def get_me(current_student: Student = Depends(get_current_student)) -> StudentMe:
    return StudentMe.model_validate(current_student, from_attributes=True)
