from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import Student
from app.routers.deps import get_current_student
from app.schemas.auth import LoginRequest, StudentMe, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    student = db.get(Student, payload.student_id)
    if not student or not verify_password(payload.password, student.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="학번 또는 비밀번호가 올바르지 않습니다.")
    token = create_access_token(str(student.student_id), {"name": student.name})
    return TokenResponse(access_token=token, student=StudentMe.model_validate(student, from_attributes=True))


@router.post("/logout")
def logout() -> dict[str, str]:
    return {"message": "로그아웃되었습니다."}


@router.get("/me", response_model=StudentMe)
def me(current_student: Student = Depends(get_current_student)) -> StudentMe:
    return StudentMe.model_validate(current_student, from_attributes=True)
