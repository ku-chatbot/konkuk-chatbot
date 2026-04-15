from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.models import AcademicDocument
from app.services.openai_client import openai_service


try:
    import faiss
except Exception:
    faiss = None


@dataclass
class RAGAnswer:
    route: str
    answer: str
    sql: None = None
    rows: list[dict] | None = None
    sources: list[str] | None = None


class RAGService:
    def answer(self, db: Session, message: str):
        docs = db.query(AcademicDocument).all()
        selected = self._search_with_embeddings(message, docs) or self._keyword_search(message, docs)
        context = "\n\n".join(f"[{doc.title}] {doc.content}" for doc in selected)
        instructions = (
            "건국대학교 학사정보 챗봇처럼 한국어로 답하세요. "
            "제공된 학사정보 문서 안에서만 답하고, 확실하지 않은 날짜나 규정은 학교 포털 확인이 필요하다고 말하세요."
        )
        llm = openai_service.complete_text(instructions, f"질문: {message}\n학사정보:\n{context}") if context else None
        if llm:
            answer = llm
        elif selected:
            answer = f"{selected[0].title} 기준으로 안내드리면, {selected[0].content}"
        else:
            answer = "내부 DB와 학사정보 문서에서 바로 확인되는 내용이 없습니다. 질문을 조금 더 구체적으로 적어주세요."
        return RAGAnswer(route="rag", answer=answer, rows=[], sources=[doc.title for doc in selected])

    def _search_with_embeddings(self, message: str, docs: list[AcademicDocument]) -> list[AcademicDocument] | None:
        query_embedding = openai_service.embed(message)
        if not query_embedding:
            return None
        doc_embeddings = []
        valid_docs = []
        for doc in docs:
            embedding = openai_service.embed(f"{doc.title}\n{doc.category}\n{doc.content}")
            if embedding:
                doc_embeddings.append(embedding)
                valid_docs.append(doc)
        if not doc_embeddings:
            return None
        matrix = np.array(doc_embeddings, dtype="float32")
        query = np.array([query_embedding], dtype="float32")
        if faiss is not None:
            faiss.normalize_L2(matrix)
            faiss.normalize_L2(query)
            index = faiss.IndexFlatIP(matrix.shape[1])
            index.add(matrix)
            _, indices = index.search(query, min(3, len(valid_docs)))
            return [valid_docs[i] for i in indices[0] if i >= 0]
        similarities = []
        q = query[0]
        q_norm = math.sqrt(float(np.dot(q, q)))
        for idx, emb in enumerate(matrix):
            denom = q_norm * math.sqrt(float(np.dot(emb, emb)))
            similarities.append((float(np.dot(q, emb)) / denom if denom else 0, idx))
        similarities.sort(reverse=True)
        return [valid_docs[idx] for _, idx in similarities[:3]]

    def _keyword_search(self, message: str, docs: list[AcademicDocument]) -> list[AcademicDocument]:
        tokens = [token for token in message.replace("?", " ").replace("!", " ").split() if len(token) > 1]
        scored = []
        for doc in docs:
            haystack = f"{doc.title} {doc.category} {doc.content}"
            score = sum(2 if token in doc.title else 1 for token in tokens if token in haystack)
            category_bonus = 2 if doc.category in message else 0
            scored.append((score + category_bonus, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [doc for score, doc in scored[:3] if score > 0] or docs[:1]


rag_service = RAGService()
