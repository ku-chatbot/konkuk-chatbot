from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from app.core.config import get_settings
from app.services.openai_client import openai_service


@dataclass
class WebSearchAnswer:
    route: str
    answer: str
    sources: list[str]


class WebSearchService:
    def is_enabled(self) -> bool:
        settings = get_settings()
        return bool(settings.enable_web_search and settings.tavily_api_key)

    def answer(self, message: str) -> WebSearchAnswer:
        clarification = self._clarify_if_too_broad(message)
        if clarification:
            return WebSearchAnswer(route="web_search", answer=clarification, sources=[])
        if not self.is_enabled():
            return WebSearchAnswer(
                route="web_search",
                answer="웹검색이 필요한 질문입니다. Tavily API 키를 설정하면 건국대학교 공식 홈페이지 기준으로 확인할 수 있어요.",
                sources=[],
            )

        try:
            results = self._search(message)
        except requests.RequestException:
            return WebSearchAnswer(
                route="web_search",
                answer="웹검색 요청 중 오류가 발생했습니다. Tavily API 키와 네트워크 상태를 확인해주세요.",
                sources=[],
            )
        official_results = [result for result in results if self._is_usable_official_result(result)]
        if not official_results:
            return WebSearchAnswer(
                route="web_search",
                answer="건국대학교 공식 홈페이지에서 확인 가능한 검색 결과를 찾지 못했습니다. 질문을 조금 더 구체적으로 적어주세요.",
                sources=[],
            )

        answer = self._summarize(message, official_results)
        sources = [self._source_label(result) for result in official_results[:3]]
        return WebSearchAnswer(route="web_search", answer=answer, sources=sources)

    def _search(self, message: str) -> list[dict]:
        all_results: list[dict] = []
        seen_urls: set[str] = set()
        for query in self._expanded_queries(message):
            for result in self._search_once(query):
                url = result.get("url") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append(result)
            if len([result for result in all_results if self._is_usable_official_result(result)]) >= 3:
                break
        return all_results

    def _search_once(self, message: str) -> list[dict]:
        settings = get_settings()
        query = message if "건국" in message or "konkuk" in message.lower() else f"건국대학교 {message}"
        payload = {
            "query": f"{query} site:konkuk.ac.kr",
            "search_depth": "advanced",
            "topic": "general",
            "include_answer": False,
            "include_raw_content": "text",
            "include_images": False,
            "max_results": 10,
        }
        response = requests.post(
            settings.tavily_search_url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            timeout=settings.tavily_request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("results") or []

    def _expanded_queries(self, message: str) -> list[str]:
        queries = [message]
        if "학과장" in message:
            queries.append(message.replace("학과장", "학부장"))
        if "컴공" in message:
            queries.append(message.replace("컴공", "컴퓨터공학부"))
        date_match = re.search(r"(\d{1,2})월(\d{1,2})일", message)
        if date_match and not re.search(r"\d{4}년", message):
            year = datetime.now(ZoneInfo("Asia/Seoul")).year
            month, day = date_match.groups()
            queries.insert(0, f"{year}년 {message}")
            queries.append(f"건국대학교 {year}학년도 학사일정 {month}월 {day}일 휴업 공휴일")
        domain_queries = []
        for query in queries:
            for domain in self._search_domains():
                domain_queries.append(f"{query} site:{domain}")
        queries.extend(domain_queries)
        return list(dict.fromkeys(queries))

    def _summarize(self, message: str, results: list[dict]) -> str:
        context_parts = []
        for idx, result in enumerate(results[:3], start=1):
            content = result.get("raw_content") or result.get("content") or ""
            context_parts.append(
                f"[{idx}] title: {result.get('title')}\n"
                f"url: {result.get('url')}\n"
                f"content:\n{content[:2500]}"
            )
        instructions = (
            "건국대학교 공식 홈페이지 검색 결과만 근거로 답하세요. "
            "검색 결과에 직접 근거가 없으면 확인하지 못했다고 답하세요. "
            f"현재/최신 정보는 검색 결과 기준이라고 표현하세요. 오늘 기준 연도는 {datetime.now(ZoneInfo('Asia/Seoul')).year}년입니다. "
            "사용자가 날짜만 말하고 연도를 말하지 않으면 오늘 기준 연도로 해석하세요. 과거 연도 결과만 있으면 현재 기준으로 확정하지 마세요. "
            "학과장/학부장 질문에서 검색 결과끼리 이름이 충돌하면 한 명으로 단정하지 말고 공식 페이지 기준으로 확정이 어렵다고 답하세요. "
            "답변 본문에는 출처 목록을 쓰지 마세요. 출처는 시스템이 별도로 표시합니다. "
            "Markdown 강조 문법(**, __)을 쓰지 마세요. 자연스러운 일반 문장으로 답하세요. "
            "한국어로 짧고 정확하게 답하세요."
        )
        generated = openai_service.complete_text(instructions, f"질문: {message}\n\n검색 결과:\n{chr(10).join(context_parts)}")
        if generated:
            return self._clean_answer(generated)
        first = results[0]
        snippet = (first.get("content") or first.get("raw_content") or "").strip()
        if snippet:
            return f"건국대학교 공식 홈페이지 검색 결과 기준으로 확인되는 내용입니다.\n\n{snippet[:500]}"
        return "건국대학교 공식 홈페이지 검색 결과는 찾았지만, 답변에 필요한 본문 내용을 확인하지 못했습니다."

    def _clean_answer(self, answer: str) -> str:
        return answer.replace("**", "").replace("__", "").strip()

    def _is_official_url(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host == "konkuk.ac.kr" or host.endswith(".konkuk.ac.kr")

    def _is_usable_official_result(self, result: dict) -> bool:
        url = result.get("url") or ""
        if not self._is_official_url(url):
            return False
        lowered_url = url.lower()
        blocked_fragments = ["/sso/", "ssologin", "failurecause", "unauthorized", "login"]
        return not any(fragment in lowered_url for fragment in blocked_fragments)

    def _search_domains(self) -> list[str]:
        settings = get_settings()
        domains = [domain.strip() for domain in settings.web_search_domains.split(",") if domain.strip()]
        return domains or ["konkuk.ac.kr"]

    def _clarify_if_too_broad(self, message: str) -> str | None:
        compact = message.replace(" ", "")
        asks_chair = "학과장" in compact or "학부장" in compact
        subject_text = compact.replace("학과장", "").replace("학부장", "")
        has_department = any(word in subject_text for word in ["컴퓨터공학부", "컴공", "경영학과", "전자공학", "기계", "화학", "국문", "영문", "학부", "학과"])
        if asks_chair and not has_department:
            return "어느 학과/학부의 학과장 또는 학부장을 알고 싶으신가요? 예: `컴퓨터공학부 학부장`, `경영학과 학과장`"
        return None

    def _source_label(self, result: dict) -> str:
        title = result.get("title") or "건국대학교 공식 홈페이지"
        url = result.get("url") or ""
        return f"{title} - {url}"


web_search_service = WebSearchService()
