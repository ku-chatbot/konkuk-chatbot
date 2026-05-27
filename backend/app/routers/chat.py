from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Student
from app.routers.deps import get_current_student
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.progress_service import progress_service
from app.services.query_service import query_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db), current_student: Student = Depends(get_current_student)) -> ChatResponse:
    try:
        result = query_service.answer(db, current_student, payload.message, request_id=payload.request_id)
        return ChatResponse(
            route=result.route,
            answer=result.answer,
            sql=None,
            rows=result.rows or [],
            sources=result.sources or [],
        )
    finally:
        progress_service.finish(payload.request_id)


@router.get("/progress/{request_id}")
def chat_progress(request_id: str, current_student: Student = Depends(get_current_student)) -> dict:
    return progress_service.get(request_id)
