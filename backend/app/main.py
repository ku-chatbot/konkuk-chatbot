from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.init_db import create_tables, seed_db
from app.db.session import SessionLocal
from app.routers import auth, chat, chat_v2, mcp, students


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    db = SessionLocal()
    try:
        seed_db(db)
    finally:
        db.close()
    yield


settings = get_settings()
app = FastAPI(title="KU-Bot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(students.router)
app.include_router(chat.router)
app.include_router(chat_v2.router)
app.include_router(mcp.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
