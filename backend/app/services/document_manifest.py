from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentSource:
    file: str
    title: str
    category: str
    url: str


def load_document_sources(path: Path) -> list[DocumentSource]:
    blocks = _split_blocks(path.read_text(encoding="utf-8"))
    sources: list[DocumentSource] = []
    for block in blocks:
        values = _parse_block(block)
        if not values:
            continue
        missing = [key for key in ("file", "title", "category", "url") if not values.get(key)]
        if missing:
            raise ValueError(f"{path} 문서 출처 항목에 누락된 필드가 있습니다: {', '.join(missing)}")
        sources.append(
            DocumentSource(
                file=values["file"],
                title=values["title"],
                category=values["category"],
                url=values["url"],
            )
        )
    return sources


def _split_blocks(text: str) -> list[str]:
    blocks = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "---":
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(raw_line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _parse_block(block: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values
