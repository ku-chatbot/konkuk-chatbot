from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Student
from app.routers.deps import get_current_student
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db), current_student: Student = Depends(get_current_student)) -> ChatResponse:
    result = chat_service.answer(db, current_student, payload.message)
    return ChatResponse(
        route=result.route,
        answer=result.answer,
        display_format=result.display_format,
        sql=result.sql,
        rows=result.rows,
        sources=result.sources,
    )
