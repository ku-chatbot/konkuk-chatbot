from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import ReferenceChunk, ReferenceDocument
from app.services.local_embedding import local_embedding_service
from app.services.openai_client import openai_service
from app.services.vector_store import reference_vector_store


@dataclass
class ReferenceSource:
    title: str
    url: str
    page: str | None = None

    def label(self) -> str:
        suffix = f", p.{self.page}" if self.page else ""
        return f"{self.title}{suffix} - {self.url}"


@dataclass
class ReferenceRAGAnswer:
    route: str
    answer: str
    sources: list[str]


class ReferenceRAGService:
    def answer(self, db: Session, message: str, top_k: int = 5) -> ReferenceRAGAnswer:
        chunks = self._retrieve(db, message, top_k)
        if not chunks:
            return ReferenceRAGAnswer(
                route="reference_rag",
                answer="아직 업로드된 참고문서에서 관련 내용을 찾지 못했습니다. 문서를 먼저 ingestion했는지 확인해주세요.",
                sources=[],
            )

        context = self._format_context(chunks)
        instructions = (
            "당신은 건국대학교 공식 참고문서 기반 챗봇입니다. "
            "제공된 문서 발췌문 안에서만 답하세요. "
            "표 내용은 빠뜨리지 말고 구조를 살려 설명하세요. "
            "문서에 없는 내용은 추측하지 말고 확인이 필요하다고 말하세요. "
            "답변 마지막에 '참고' 섹션을 만들고 제공된 출처 제목, 페이지, URL을 포함하세요."
        )
        llm = openai_service.complete_text(instructions, f"질문: {message}\n\n참고문서:\n{context}")
        answer = llm or self._fallback_answer(chunks)
        return ReferenceRAGAnswer(route="reference_rag", answer=answer, sources=[source.label() for source in self._sources(chunks)])

    def _retrieve(self, db: Session, message: str, top_k: int) -> list[ReferenceChunk]:
        query_vector = local_embedding_service.embed(message)
        results = reference_vector_store.search(query_vector, top_k=top_k)
        if not results:
            return []
        vector_ids = [result.vector_id for result in results]
        chunks_by_vector_id = {
            chunk.vector_id: chunk
            for chunk in db.query(ReferenceChunk)
            .join(ReferenceDocument)
            .filter(ReferenceDocument.status == "ready", ReferenceChunk.vector_id.in_(vector_ids))
            .all()
        }
        return [chunks_by_vector_id[vector_id] for vector_id in vector_ids if vector_id in chunks_by_vector_id]

    def _format_context(self, chunks: list[ReferenceChunk]) -> str:
        parts = []
        for idx, chunk in enumerate(chunks, start=1):
            document = chunk.document
            page = _page_label(chunk)
            page_text = f" / page: {page}" if page else ""
            heading = f" / heading: {chunk.heading}" if chunk.heading else ""
            parts.append(
                f"[{idx}] title: {document.title}{page_text}{heading}\n"
                f"url: {document.source_url}\n"
                f"content:\n{chunk.content}"
            )
        return "\n\n".join(parts)

    def _sources(self, chunks: list[ReferenceChunk]) -> list[ReferenceSource]:
        seen: set[tuple[str, str, str | None]] = set()
        sources: list[ReferenceSource] = []
        for chunk in chunks:
            source = ReferenceSource(title=chunk.document.title, url=chunk.document.source_url, page=_page_label(chunk))
            key = (source.title, source.url, source.page)
            if key in seen:
                continue
            seen.add(key)
            sources.append(source)
        return sources

    def _fallback_answer(self, chunks: list[ReferenceChunk]) -> str:
        first = chunks[0]
        source = ReferenceSource(first.document.title, first.document.source_url, _page_label(first))
        return f"{first.document.title} 기준으로 확인되는 내용입니다.\n\n{first.content[:800]}\n\n참고\n- {source.label()}"


def _page_label(chunk: ReferenceChunk) -> str | None:
    if chunk.page_start is None:
        return None
    if chunk.page_end and chunk.page_end != chunk.page_start:
        return f"{chunk.page_start}-{chunk.page_end}"
    return str(chunk.page_start)


reference_rag_service = ReferenceRAGService()
