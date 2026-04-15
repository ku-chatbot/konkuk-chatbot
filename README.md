# KU-Bot

자연어 질문을 내부 학사 DB 또는 학사정보 문서 검색으로 답변하는 건국대학교 학사정보 챗봇 프로토타입입니다.

## 구조

```text
backend/   FastAPI, SQLite, 인증, Text-to-SQL, MCP 역할 API, 학사정보 RAG
frontend/  React, 로그인 화면, 챗봇 UI
참고자료/  원본 참고자료 보관
```

## 답변 흐름

1. 사용자가 로그인합니다.
2. 질문이 들어오면 먼저 내부 DB로 답할 수 있는지 판단합니다.
3. 수강 과목, 성적, 시간표, 등록금, 교수 정보, 선수과목처럼 DB 기반 질문이면 SQL을 생성/검증/실행합니다.
4. 휴학, 복학, 장학, 졸업요건, 수강정정 같은 일반 학사정보 질문이면 학사 문서 검색 결과를 바탕으로 답변합니다.
5. 모든 DB 조회는 로그인한 `student_id` 기준으로 제한합니다.

## 실행

백엔드:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

프론트엔드:

```bash
cd frontend
npm install
npm run dev
```

## OpenAI 설정

`backend/.env`의 `OPENAI_API_KEY`를 입력하면 OpenAI Responses API로 Text-to-SQL과 자연어 답변을 생성하고, Embeddings API로 학사정보 문서를 검색합니다. 키가 없어도 규칙 기반 SQL과 키워드 검색으로 기본 데모는 동작합니다.

## 테스트 계정

- 학번: `202214001`부터 `202214100`
- 비밀번호: `password123`
