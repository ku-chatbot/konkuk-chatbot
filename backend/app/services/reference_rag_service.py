from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import ReferenceChunk, ReferenceDocument
from app.services.embedding_client import embedding_client
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
    def answer(self, db: Session, message: str, top_k: int = 5, domain: str | None = None, domains: list[str] | None = None, intent: str | None = None) -> ReferenceRAGAnswer:
        domain = domain or _infer_domain(message)
        domains = domains or _infer_domains(message)
        intent = intent or _infer_intent(message)
        chunks = self._retrieve_for_domains(db, message, domains, top_k)
        chunks = self._augment_action_path_chunks(db, message, chunks)
        chunks = self._filter_chunks_by_domains(chunks, domains, intent)
        if not chunks:
            return ReferenceRAGAnswer(
                route="reference_rag",
                answer="연결된 공식 참고문서에서 해당 주제에 맞는 근거를 찾지 못했습니다. 질문을 조금 더 구체적으로 적거나, 최신 공지성 정보라면 학교 홈페이지 공지사항을 확인해주세요.",
                sources=[],
            )
        if not self._has_enough_evidence(message, chunks):
            return ReferenceRAGAnswer(
                route="reference_rag",
                answer="연결된 공식 참고문서에서 해당 내용을 확인하지 못했습니다. 질문을 조금 더 구체적으로 적거나, 최신 공지성 정보라면 학교 홈페이지 공지사항을 확인해주세요.",
                sources=[],
            )

        context = self._format_context(chunks)
        instructions = (
            "당신은 건국대학교 공식 참고문서 기반 챗봇입니다. "
            "제공된 문서 발췌문 안에서만 답하세요. "
            f"현재 질문 주제(domains)는 {domains}, 대표 주제(domain)는 {domain}, 의도(intent)는 {intent}입니다. "
            "질문 주제와 다른 제도나 메뉴를 섞어 답하지 마세요. "
            "여러 주제가 함께 들어온 질문이면 주제별로 확인된 내용을 나누어 답하세요. "
            "질문에 직접 답할 근거가 부족하면 answerable=false로 반환하고 답을 꾸며내지 마세요. "
            "문서에 없는 내용은 추측하지 말고 확인이 필요하다고 말하세요. "
            "답변 본문에는 출처/참고 섹션을 만들지 마세요. 출처는 시스템이 별도로 표시합니다. "
            "사용자가 바로 행동할 수 있도록 짧고 실용적으로 답하세요. "
            "'신청하는 법', '어디서 신청', '신청 링크', '경로'를 묻는 질문은 제도 설명보다 접속 위치와 메뉴 경로를 먼저 답하세요. "
            "특히 학사정보시스템과 메뉴 경로가 참고문서에 있으면 summary 첫 문장과 steps 1번에 반드시 먼저 포함하세요. "
            "직접 URL이나 세부 메뉴가 참고문서에 없으면 다른 제도의 링크로 대체하지 말고, 문서에서 확인되지 않는다고 말하세요. "
            "반드시 JSON만 반환하세요: "
            "{\"answerable\": boolean, \"summary\": string, \"steps\": string[], \"notes\": string[], "
            "\"followup_question\": string|null, \"used_source_indices\": number[]}. "
            "summary는 1~2문장, steps는 0~5개, notes는 0~5개로 제한하세요. "
            "used_source_indices는 실제 답변에 사용한 참고문서 번호만 1부터 시작하는 숫자로 넣으세요."
        )
        data = openai_service.complete_json(instructions, f"질문: {message}\n\n참고문서:\n{context}")
        if data and data.get("answerable") is False:
            return ReferenceRAGAnswer(
                route="reference_rag",
                answer="연결된 공식 참고문서에서 해당 내용을 확인하지 못했습니다. 질문을 조금 더 구체적으로 적어주세요.",
                sources=[],
            )
        answer = self._render_answer(data, message) if data else self._fallback_answer(chunks)
        sources = self._selected_sources(chunks, data)
        return ReferenceRAGAnswer(route="reference_rag", answer=answer, sources=[source.label() for source in sources])

    def _retrieve_for_domains(self, db: Session, message: str, domains: list[str], top_k: int) -> list[ReferenceChunk]:
        queries = [message]
        for domain in domains:
            hint = _domain_search_hint(domain)
            if hint:
                queries.append(f"{message} {hint}")
        chunks: list[ReferenceChunk] = []
        seen_ids: set[int] = set()
        for query in dict.fromkeys(queries):
            for chunk in self._retrieve(db, query, top_k):
                if chunk.id in seen_ids:
                    continue
                seen_ids.add(chunk.id)
                chunks.append(chunk)
        return chunks

    def _filter_chunks_by_domains(self, chunks: list[ReferenceChunk], domains: list[str], intent: str) -> list[ReferenceChunk]:
        filter_domains = [domain for domain in domains if domain not in {"unknown", "course", "professor", "grade", "schedule", "tuition", "event"}]
        if not filter_domains:
            return chunks
        filtered = [chunk for chunk in chunks if any(_chunk_matches_domain(chunk, domain, intent) for domain in filter_domains)]
        return filtered

    def _retrieve(self, db: Session, message: str, top_k: int) -> list[ReferenceChunk]:
        query_vector = embedding_client.embed(message)
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

    def _augment_action_path_chunks(self, db: Session, message: str, chunks: list[ReferenceChunk]) -> list[ReferenceChunk]:
        compact = message.replace(" ", "")
        asks_action_path = any(word in compact for word in ["어떻게", "하는법", "방법", "신청하는법", "어디서신청", "신청링크", "신청하는곳", "링크", "경로", "홈페이지", "사이트", "포털", "학사정보시스템"])
        if "휴학" not in message or "신청" not in message or not asks_action_path:
            return chunks
        leave_chunk = (
            db.query(ReferenceChunk)
            .join(ReferenceDocument)
            .filter(
                ReferenceDocument.status == "ready",
                ReferenceChunk.content.contains("휴학신청 방법 및 제출 대상 서류"),
            )
            .order_by(ReferenceChunk.id)
            .first()
        )
        portal_chunk = (
            db.query(ReferenceChunk)
            .join(ReferenceDocument)
            .filter(
                ReferenceDocument.status == "ready",
                ReferenceChunk.content.contains("건국대학교 학사정보시스템(kuis.konkuk.ac.kr)"),
                ReferenceChunk.content.contains("휴복학 신청"),
            )
            .order_by(ReferenceChunk.id)
            .first()
        )
        priority_chunks = [chunk for chunk in [leave_chunk, portal_chunk] if chunk is not None]
        priority_ids = {chunk.id for chunk in priority_chunks}
        remaining_chunks = [chunk for chunk in chunks if chunk.id not in priority_ids]
        return priority_chunks + remaining_chunks

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

    def _selected_sources(self, chunks: list[ReferenceChunk], data: dict | None) -> list[ReferenceSource]:
        if not data:
            return self._sources(chunks[:1])
        raw_indices = data.get("used_source_indices") or []
        selected_chunks = []
        for raw in raw_indices:
            if not isinstance(raw, int):
                continue
            index = raw - 1
            if 0 <= index < len(chunks):
                selected_chunks.append(chunks[index])
        return self._sources(selected_chunks or chunks[:1])

    def _has_enough_evidence(self, message: str, chunks: list[ReferenceChunk]) -> bool:
        compact = message.replace(" ", "")
        protected_keywords = [
            "휴학",
            "복학",
            "장학",
            "졸업",
            "수강신청",
            "수강정정",
            "전과",
            "다전공",
            "부전공",
            "교환학생",
            "국제교류",
            "등록금",
            "학사정보시스템",
            "장학복지팀",
            "연락처",
        ]
        if any(keyword in compact for keyword in protected_keywords):
            joined = "\n".join(chunk.content for chunk in chunks)
            return any(keyword in joined.replace(" ", "") for keyword in protected_keywords if keyword in compact)
        terms = [term for term in _query_terms(message) if len(term) >= 2]
        if not terms:
            return False
        joined = "\n".join(chunk.content for chunk in chunks).replace(" ", "").lower()
        matched = sum(1 for term in terms if term.lower() in joined)
        return matched >= min(2, len(terms))

    def _render_answer(self, data: dict, message: str) -> str:
        summary = _clean_text(data.get("summary")) or "공식 참고문서 기준으로 확인되는 내용입니다."
        action_path = _leave_action_path(message)
        if action_path and not summary.startswith("학사정보시스템"):
            summary = f"{action_path} {summary}"
        lines = [summary]
        if _wants_concise_fact(message):
            notes = _clean_list(data.get("notes"))
            if notes:
                lines.append("\n확인할 점")
                lines.extend(f"- {note}" for note in notes[:3])
            return "\n".join(lines)
        steps = _clean_list(data.get("steps"))
        if action_path:
            steps = [step for step in steps if "학사정보시스템" not in step and "kuis.konkuk.ac.kr" not in step]
            steps.insert(0, action_path)
        if steps:
            lines.append("\n바로 할 일")
            lines.extend(f"{idx}. {step}" for idx, step in enumerate(steps, start=1))
        notes = _clean_list(data.get("notes"))
        if notes:
            lines.append("\n주의할 점")
            lines.extend(f"- {note}" for note in notes)
        followup = _clean_text(data.get("followup_question"))
        if followup:
            lines.append(f"\n{followup}")
        return "\n".join(lines)

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


def _clean_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _clean_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def _query_terms(message: str) -> list[str]:
    stopwords = {
        "알려줘",
        "어떻게",
        "어디서",
        "언제",
        "뭐야",
        "무엇",
        "하는법",
        "방법",
        "신청",
        "확인",
        "관련",
        "기준",
    }
    raw_terms = re.findall(r"[가-힣A-Za-z0-9+]+", message)
    return [term for term in raw_terms if term not in stopwords]


def _wants_concise_fact(message: str) -> bool:
    compact = message.replace(" ", "")
    return any(word in compact for word in ["가능횟수", "몇번", "몇회", "얼마나", "누구", "무엇"]) and not any(
        word in compact for word in ["신청", "방법", "어떻게", "절차", "경로", "어디서"]
    )


def _leave_action_path(message: str) -> str | None:
    compact = message.replace(" ", "")
    asks_action_path = any(word in compact for word in ["어떻게", "하는법", "방법", "신청하는법", "어디서신청", "신청링크", "신청하는곳", "링크", "경로", "홈페이지", "사이트", "포털", "학사정보시스템"])
    if "휴학" in message and "신청" in message and asks_action_path:
        return "학사정보시스템(kuis.konkuk.ac.kr) 접속 후 `학적` 메뉴의 학적변동 신청(휴복학 신청)에서 진행하세요."
    return None


def _infer_domain(message: str) -> str:
    return _infer_domains(message)[0]


def _infer_domains(message: str) -> list[str]:
    compact = message.replace(" ", "")
    domain_keywords = [
        ("leave", ["휴학", "미등록", "입대휴학", "가사휴학", "질병휴학", "육아휴학", "창업휴학"]),
        ("return", ["복학"]),
        ("graduation", ["졸업", "졸업요건", "졸업유예", "졸업가능", "졸업시뮬레이션"]),
        ("course_registration", ["수강신청", "수강정정", "수강바구니", "계절학기", "전공인정", "학점인정"]),
        ("scholarship", ["장학", "장학금", "장학복지팀"]),
        ("international", ["교환학생", "국제교류"]),
        ("tuition", ["등록금"]),
    ]
    domains = []
    for domain, keywords in domain_keywords:
        if any(keyword in compact for keyword in keywords):
            domains.append(domain)
    return domains or ["unknown"]


def _domain_search_hint(domain: str) -> str | None:
    hints = {
        "leave": "가사휴학 재학 중 통산 6학기 휴학 가능 기간",
        "graduation": "졸업유예 2회 1학기씩 총 1년 졸업 요건",
        "course_registration": "수강신청 수강정정 수강바구니 기간",
        "scholarship": "장학금 장학복지팀 연락처",
        "international": "교환학생 국제교류",
        "tuition": "등록금 납부",
    }
    return hints.get(domain)


def _infer_intent(message: str) -> str:
    compact = message.replace(" ", "")
    if any(word in compact for word in ["언제", "언제까지", "기간", "몇일까지", "마감"]):
        return "deadline"
    if any(word in compact for word in ["어디", "경로", "링크", "홈페이지", "사이트", "확인", "조회", "보려면"]):
        return "location"
    if any(word in compact for word in ["서류", "준비물", "필요"]):
        return "documents"
    if any(word in compact for word in ["방법", "어떻게", "하는법", "신청"]):
        return "method"
    if any(word in compact for word in ["몇번", "몇회", "가능횟수", "얼마나"]):
        return "count"
    return "lookup"


def _chunk_matches_domain(chunk: ReferenceChunk, domain: str, intent: str) -> bool:
    text = f"{chunk.document.title} {chunk.document.category} {chunk.heading or ''} {chunk.content}".replace(" ", "")
    keyword_map = {
        "leave": ["휴학", "휴복학", "입대휴학", "가사휴학", "질병휴학", "육아휴학", "창업휴학"],
        "return": ["복학", "휴복학"],
        "graduation": ["졸업", "졸업요건", "졸업가능여부", "졸업시뮬레이션", "취득학점확인원", "졸업유예"],
        "course_registration": ["수강신청", "수강정정", "수강바구니", "계절학기", "전공인정", "학점인정"],
        "scholarship": ["장학", "장학금", "장학복지팀"],
        "international": ["국제교류", "교환학생"],
        "tuition": ["등록금", "납부"],
    }
    if any(keyword in text for keyword in keyword_map.get(domain, [])):
        return True
    if intent == "location" and domain == "leave":
        return "학사정보시스템" in text and "휴복학" in text
    if intent == "location" and domain == "graduation":
        return "학사정보시스템" in text and ("졸업" in text or "취득학점확인원" in text)
    return False
