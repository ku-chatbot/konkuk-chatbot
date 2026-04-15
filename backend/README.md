# KU-Bot Backend

FastAPI 기반 학사정보 챗봇 백엔드입니다. 내부 SQLite DB로 답할 수 있는 질문을 먼저 처리하고, DB로 답하기 어려운 학사정보 질문은 학사 문서 검색(RAG)으로 답합니다.

## 실행

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

OpenAI API를 사용하려면 `.env`의 `OPENAI_API_KEY`를 채우세요. 키가 없어도 규칙 기반 SQL과 키워드 학사정보 검색으로 데모가 동작합니다.

## 테스트 계정

- 학번: `202214001`부터 `202214100`
- 비밀번호: `password123`

## 주요 API

- `POST /auth/login`
- `GET /students/me`
- `POST /chat`
- `GET /mcp/schema`
- `POST /mcp/query`
