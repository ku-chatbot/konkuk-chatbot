from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ParsedChunk:
    content: str
    page_start: int | None = None
    page_end: int | None = None
    heading: str | None = None


def extract_markdown(parse_result: dict[str, Any]) -> str:
    content = parse_result.get("content")
    if isinstance(content, dict):
        for key in ("markdown", "text"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("markdown", "text"):
        value = parse_result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "\n\n".join(chunk.content for chunk in extract_chunks(parse_result))


def extract_html(parse_result: dict[str, Any]) -> str:
    content = parse_result.get("content")
    if isinstance(content, dict):
        value = content.get("html")
        if isinstance(value, str):
            return value
    value = parse_result.get("html")
    return value if isinstance(value, str) else ""


def extract_chunks(parse_result: dict[str, Any], max_chars: int = 1800) -> list[ParsedChunk]:
    element_chunks = _chunks_from_elements(parse_result)
    if element_chunks:
        return _merge_small_chunks(element_chunks, max_chars)
    markdown = extract_markdown(parse_result)
    return _split_markdown(markdown, max_chars)


def _chunks_from_elements(parse_result: dict[str, Any]) -> list[ParsedChunk]:
    elements = parse_result.get("elements")
    if not isinstance(elements, list):
        return []
    chunks: list[ParsedChunk] = []
    current_heading: str | None = None
    for element in elements:
        if not isinstance(element, dict):
            continue
        text = _element_text(element)
        if not text:
            continue
        category = str(element.get("category") or element.get("type") or "").lower()
        if "heading" in category or category in {"title", "header"}:
            current_heading = text[:200]
        chunks.append(ParsedChunk(content=text, page_start=_element_page(element), page_end=_element_page(element), heading=current_heading))
    return chunks


def _element_text(element: dict[str, Any]) -> str:
    content = element.get("content")
    candidates: list[Any] = []
    if isinstance(content, dict):
        candidates.extend([content.get("markdown"), content.get("text"), content.get("html")])
    candidates.extend([element.get("markdown"), element.get("text"), element.get("html")])
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _element_page(element: dict[str, Any]) -> int | None:
    for key in ("page", "page_number", "page_no"):
        value = element.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    coordinates = element.get("coordinates") or element.get("bounding_box")
    if isinstance(coordinates, dict):
        value = coordinates.get("page") or coordinates.get("page_number")
        if isinstance(value, int):
            return value
    return None


def _merge_small_chunks(chunks: list[ParsedChunk], max_chars: int) -> list[ParsedChunk]:
    merged: list[ParsedChunk] = []
    buffer: list[str] = []
    page_start: int | None = None
    page_end: int | None = None
    heading: str | None = None

    def flush() -> None:
        nonlocal buffer, page_start, page_end, heading
        text = "\n\n".join(buffer).strip()
        if text:
            merged.append(ParsedChunk(content=text, page_start=page_start, page_end=page_end, heading=heading))
        buffer = []
        page_start = None
        page_end = None
        heading = None

    for chunk in chunks:
        if buffer and len("\n\n".join(buffer)) + len(chunk.content) > max_chars:
            flush()
        buffer.append(chunk.content)
        heading = heading or chunk.heading
        if chunk.page_start is not None:
            page_start = chunk.page_start if page_start is None else min(page_start, chunk.page_start)
            page_end = chunk.page_end if page_end is None else max(page_end, chunk.page_end or chunk.page_start)
    flush()
    return merged


def _split_markdown(markdown: str, max_chars: int) -> list[ParsedChunk]:
    if not markdown.strip():
        return []
    parts: list[ParsedChunk] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n\n".join(buffer).strip()
        if text:
            for piece in _split_long_text(text, max_chars):
                parts.append(ParsedChunk(content=piece, heading=heading))
        buffer = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()[:200] or heading
        buffer.append(line)
        if len("\n".join(buffer)) >= max_chars:
            flush()
    flush()
    return parts


def _split_long_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces = []
    paragraphs = text.split("\n\n")
    buffer: list[str] = []
    for paragraph in paragraphs:
        if buffer and len("\n\n".join(buffer)) + len(paragraph) > max_chars:
            pieces.append("\n\n".join(buffer).strip())
            buffer = []
        if len(paragraph) > max_chars:
            pieces.extend(paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars))
        else:
            buffer.append(paragraph)
    if buffer:
        pieces.append("\n\n".join(buffer).strip())
    return [piece for piece in pieces if piece]
