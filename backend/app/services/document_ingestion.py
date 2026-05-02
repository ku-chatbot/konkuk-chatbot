from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import ReferenceChunk, ReferenceDocument
from app.services.document_manifest import DocumentSource, load_document_sources
from app.services.document_parser import extract_chunks, extract_html, extract_markdown
from app.services.local_embedding import local_embedding_service
from app.services.upstage_client import upstage_document_parser
from app.services.vector_store import reference_vector_store


RAW_DOCUMENTS_DIR = Path("data/raw_documents")
PARSED_DOCUMENTS_DIR = Path("data/parsed_documents")
MANIFEST_PATH = RAW_DOCUMENTS_DIR / "source_urls.txt"


def ingest_reference_documents(db: Session, manifest_path: Path = MANIFEST_PATH, raw_dir: Path = RAW_DOCUMENTS_DIR) -> dict[str, int]:
    sources = load_document_sources(manifest_path)
    PARSED_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"documents": 0, "chunks": 0, "failed": 0}

    for source in sources:
        print(f"[ingest] {source.file}", flush=True)
        try:
            document, chunk_count = _ingest_one(db, source, raw_dir)
            stats["documents"] += 1
            stats["chunks"] += chunk_count
            document.status = "ready"
            document.error = None
            db.commit()
        except Exception as exc:
            stats["failed"] += 1
            db.rollback()
            document = db.query(ReferenceDocument).filter(ReferenceDocument.file_path == source.file).first()
            if document:
                document.status = "failed"
                document.error = str(exc)
                db.commit()
            print(f"[ingest failed] {source.file}: {exc}", flush=True)

    print("[ingest] rebuilding FAISS index", flush=True)
    _rebuild_vector_index(db)
    return stats


def _ingest_one(db: Session, source: DocumentSource, raw_dir: Path) -> tuple[ReferenceDocument, int]:
    pdf_path = raw_dir / source.file
    document = db.query(ReferenceDocument).filter(ReferenceDocument.file_path == source.file).first()
    if document and document.status == "ready" and document.chunks:
        return document, len(document.chunks)
    if document is None:
        document = ReferenceDocument(file_path=source.file, title=source.title, category=source.category, source_url=source.url)
        db.add(document)
        db.flush()
    else:
        document.title = source.title
        document.category = source.category
        document.source_url = source.url
        document.status = "parsing"
        db.query(ReferenceChunk).filter(ReferenceChunk.document_id == document.id).delete()
        db.flush()

    parse_result = upstage_document_parser.parse(pdf_path)
    output_stem = _safe_stem(source.file)
    raw_response_path = PARSED_DOCUMENTS_DIR / f"{output_stem}.json"
    markdown_path = PARSED_DOCUMENTS_DIR / f"{output_stem}.md"
    html_path = PARSED_DOCUMENTS_DIR / f"{output_stem}.html"

    raw_response_path.write_text(json.dumps(parse_result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(extract_markdown(parse_result), encoding="utf-8")
    html_path.write_text(extract_html(parse_result), encoding="utf-8")

    document.parsed_markdown_path = str(markdown_path)
    document.parsed_html_path = str(html_path)
    document.raw_response_path = str(raw_response_path)

    parsed_chunks = extract_chunks(parse_result)
    if not parsed_chunks:
        raise RuntimeError("파싱 결과에서 검색용 chunk를 만들 수 없습니다.")

    for index, parsed in enumerate(parsed_chunks):
        chunk = ReferenceChunk(
            document_id=document.id,
            chunk_index=index,
            content=parsed.content,
            page_start=parsed.page_start,
            page_end=parsed.page_end,
            heading=parsed.heading,
            token_count=len(parsed.content.split()),
        )
        db.add(chunk)
    db.flush()
    chunks = db.query(ReferenceChunk).filter(ReferenceChunk.document_id == document.id).order_by(ReferenceChunk.chunk_index).all()
    for chunk in chunks:
        chunk.vector_id = chunk.id
    db.flush()
    return document, len(chunks)


def _rebuild_vector_index(db: Session) -> None:
    rows = (
        db.query(ReferenceChunk.vector_id, ReferenceChunk.content)
        .join(ReferenceDocument)
        .filter(ReferenceDocument.status == "ready", ReferenceChunk.vector_id.isnot(None))
        .order_by(ReferenceChunk.id)
        .all()
    )
    if not rows:
        return
    vector_ids = [int(row.vector_id) for row in rows if row.vector_id is not None]
    texts = [_embedding_text(row.content) for row in rows if row.vector_id is not None]
    db.close()
    vectors = local_embedding_service.embed_many(texts)
    reference_vector_store.save(vectors, vector_ids)


def _safe_stem(file_path: str) -> str:
    return file_path.replace("/", "__").rsplit(".", 1)[0]


def _embedding_text(text: str, max_chars: int = 2500) -> str:
    # NOTE: document_parser.extract_chunks(max_chars=1800)보다 커야 검색 임베딩과
    # LLM 컨텍스트가 일치한다. 청크 크기를 늘릴 경우 이 값도 함께 조정.
    return text[:max_chars]
