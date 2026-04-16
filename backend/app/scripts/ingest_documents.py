from app.db.init_db import create_tables
from app.db.session import SessionLocal
from app.services.document_ingestion import ingest_reference_documents


def main() -> None:
    create_tables()
    db = SessionLocal()
    try:
        stats = ingest_reference_documents(db)
    finally:
        db.close()
    print(f"ingestion complete: documents={stats['documents']} chunks={stats['chunks']} failed={stats['failed']}")


if __name__ == "__main__":
    main()
