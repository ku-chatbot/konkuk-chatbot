from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import requests

from app.core.config import get_settings


class UpstageDocumentParseError(RuntimeError):
    pass


class UpstageDocumentParser:
    def parse(self, pdf_path: Path) -> dict[str, Any]:
        try:
            return self.parse_sync(pdf_path)
        except UpstageDocumentParseError as exc:
            print(f"[upstage] sync parse failed, trying async: {exc}", flush=True)
            return self.parse_async(pdf_path)

    def parse_sync(self, pdf_path: Path) -> dict[str, Any]:
        settings = get_settings()
        if not settings.upstage_api_key:
            raise UpstageDocumentParseError("UPSTAGE_API_KEY가 설정되어 있지 않습니다.")
        if not pdf_path.exists():
            raise UpstageDocumentParseError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

        headers = {"Authorization": f"Bearer {settings.upstage_api_key}"}
        data = {
            "model": "document-parse",
            "ocr": "auto",
            "coordinates": "true",
            "chart_recognition": "true",
            "output_formats": '["markdown","html"]',
        }
        with pdf_path.open("rb") as pdf_file:
            response = requests.post(
                settings.upstage_parse_url,
                headers=headers,
                data=data,
                files={"document": (pdf_path.name, pdf_file, "application/pdf")},
                timeout=180,
            )
        if response.status_code >= 400:
            raise UpstageDocumentParseError(f"Upstage parse 실패: {response.status_code} {response.text[:500]}")
        try:
            return response.json()
        except ValueError as exc:
            raise UpstageDocumentParseError("Upstage 응답을 JSON으로 해석할 수 없습니다.") from exc

    def parse_async(self, pdf_path: Path, poll_interval: int = 10, timeout_seconds: int = 1800) -> dict[str, Any]:
        settings = get_settings()
        if not settings.upstage_api_key:
            raise UpstageDocumentParseError("UPSTAGE_API_KEY가 설정되어 있지 않습니다.")
        if not pdf_path.exists():
            raise UpstageDocumentParseError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

        headers = {"Authorization": f"Bearer {settings.upstage_api_key}"}
        data = {
            "model": "document-parse",
            "ocr": "auto",
            "coordinates": "true",
            "chart_recognition": "true",
            "output_formats": '["markdown","html"]',
        }
        async_url = settings.upstage_parse_url.rstrip("/") + "/async"
        with pdf_path.open("rb") as pdf_file:
            response = requests.post(
                async_url,
                headers=headers,
                data=data,
                files={"document": (pdf_path.name, pdf_file, "application/pdf")},
                timeout=180,
            )
        if response.status_code >= 400:
            raise UpstageDocumentParseError(f"Upstage async 요청 실패: {response.status_code} {response.text[:500]}")
        payload = _json_response(response, "Upstage async 요청 응답을 JSON으로 해석할 수 없습니다.")
        request_id = payload.get("request_id")
        if not request_id:
            raise UpstageDocumentParseError(f"Upstage async 응답에 request_id가 없습니다: {payload}")

        status_url = settings.upstage_parse_url.rstrip("/").rsplit("/", 1)[0] + f"/requests/{request_id}"
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status_response = requests.get(status_url, headers=headers, timeout=60)
            if status_response.status_code >= 400:
                raise UpstageDocumentParseError(f"Upstage async 상태 조회 실패: {status_response.status_code} {status_response.text[:500]}")
            status_payload = _json_response(status_response, "Upstage async 상태 응답을 JSON으로 해석할 수 없습니다.")
            status = str(status_payload.get("status", "")).lower()
            print(f"[upstage] async status={status or 'unknown'} request_id={request_id}", flush=True)
            if status in {"completed", "succeeded", "success", "done"}:
                return self._download_async_result(status_payload)
            if status in {"failed", "error", "canceled", "cancelled"}:
                raise UpstageDocumentParseError(f"Upstage async 파싱 실패: {status_payload}")
            time.sleep(poll_interval)
        raise UpstageDocumentParseError(f"Upstage async 파싱 제한시간 초과: request_id={request_id}")

    def _download_async_result(self, status_payload: dict[str, Any]) -> dict[str, Any]:
        download_urls = _collect_download_urls(status_payload)
        if not download_urls:
            if "content" in status_payload or "elements" in status_payload:
                return status_payload
            raise UpstageDocumentParseError(f"Upstage async 완료 응답에 download_url이 없습니다: {status_payload}")

        results = []
        for url in download_urls:
            response = requests.get(url, timeout=180)
            if response.status_code >= 400:
                raise UpstageDocumentParseError(f"Upstage async 결과 다운로드 실패: {response.status_code} {response.text[:500]}")
            results.append(_json_response(response, "Upstage async 다운로드 결과를 JSON으로 해석할 수 없습니다."))
        if len(results) == 1:
            return results[0]
        return _merge_parse_results(results)


def _json_response(response: requests.Response, error_message: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise UpstageDocumentParseError(error_message) from exc
    if not isinstance(data, dict):
        raise UpstageDocumentParseError(f"{error_message}: {data}")
    return data


def _collect_download_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    direct = payload.get("download_url")
    if isinstance(direct, str):
        urls.append(direct)
    for key in ("batches", "batch_results", "results", "files"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            url = item.get("download_url") or item.get("url")
            if isinstance(url, str):
                urls.append(url)
    return urls


def _merge_parse_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {"content": {"markdown": "", "html": ""}, "elements": []}
    page_offset = 0
    total_pages = 0
    for result in results:
        content = result.get("content") if isinstance(result.get("content"), dict) else {}
        markdown = content.get("markdown") or result.get("markdown") or ""
        html = content.get("html") or result.get("html") or ""
        if markdown:
            merged["content"]["markdown"] += ("\n\n" if merged["content"]["markdown"] else "") + str(markdown)
        if html:
            merged["content"]["html"] += ("\n\n" if merged["content"]["html"] else "") + str(html)
        elements = result.get("elements")
        if isinstance(elements, list):
            for element in elements:
                if isinstance(element, dict):
                    copied = dict(element)
                    page = copied.get("page")
                    if isinstance(page, int):
                        copied["page"] = page + page_offset
                    merged["elements"].append(copied)
        pages = _usage_pages(result)
        page_offset += pages
        total_pages += pages
    merged["usage"] = {"pages": total_pages}
    return merged


def _usage_pages(result: dict[str, Any]) -> int:
    usage = result.get("usage")
    if isinstance(usage, dict):
        pages = usage.get("pages")
        if isinstance(pages, int):
            return pages
        if isinstance(pages, str) and pages.isdigit():
            return int(pages)
    elements = result.get("elements")
    if isinstance(elements, list):
        pages = [element.get("page") for element in elements if isinstance(element, dict) and isinstance(element.get("page"), int)]
        return max(pages) if pages else 0
    return 0


upstage_document_parser = UpstageDocumentParser()
