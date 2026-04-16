from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Student
from app.routers.deps import get_current_student
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.reference_rag_service import reference_rag_service

router = APIRouter(prefix="/chat-v2", tags=["chat-v2"])


@router.post("", response_model=ChatResponse)
def chat_v2(payload: ChatRequest, db: Session = Depends(get_db), current_student: Student = Depends(get_current_student)) -> ChatResponse:
    result = reference_rag_service.answer(db, payload.message)
    return ChatResponse(route=result.route, answer=result.answer, rows=[], sources=result.sources)
