# KU-Bot

자연어 질문을 내부 학사 DB, 공식 학사문서 RAG, 건국대학교 공식 홈페이지 웹검색으로 분기해 답변하는 건국대학교 학사정보 챗봇 프로토타입입니다.

## 구조

```text
backend/   FastAPI, SQLite, 인증, DB/RAG/Web 라우팅, FAISS 벡터 검색, 임베딩 서버
frontend/  React, 로그인 화면, 챗봇 UI, 답변 진행 상태 표시
참고자료/  공식 PDF/문서 원본 보관
```

## 답변 흐름

1. 사용자가 로그인합니다.
2. 질문을 DB, 공식문서 RAG, 웹검색, planner 중 어디로 보낼지 분류합니다.
3. 수강 과목, 성적, 시간표, 등록금, 교수 정보, 선수과목처럼 DB 기반 질문은 SQLite를 조회합니다.
4. 휴학, 복학, 장학, 졸업요건, 수강정정 같은 학사정보 질문은 `reference_document/reference_chunk`와 FAISS 인덱스로 공식 문서를 검색합니다.
5. 학과장, 최신 공지, 행사 일정처럼 최신성이 필요한 질문은 Tavily API가 켜져 있을 때 건국대학교 공식 도메인을 검색합니다.
6. 계절학기 전공 인정, 과목 추천처럼 DB와 문서 근거를 함께 봐야 하는 질문은 planner가 과목 DB, RAG, 웹검색 근거를 모아 답변합니다.
7. 모든 개인정보성 DB 조회는 로그인한 `student_id` 기준으로 제한합니다.

프론트는 `/chat/progress/{request_id}`를 폴링해 현재 처리 단계와 planner 검색 키워드를 보여줍니다.

## 실행

### 1. 백엔드 설정

```bash
cd backend
conda activate kubot-py312
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 필요한 값을 채웁니다.

```bash
OPENAI_API_KEY=...
ENABLE_WEB_SEARCH=false
TAVILY_API_KEY=
```

### 2. 임베딩 서버 실행

공식 문서 RAG는 로컬 임베딩 서버를 사용합니다.

```bash
cd backend
TOKENIZERS_PARALLELISM=false \
OMP_NUM_THREADS=1 \
MKL_NUM_THREADS=1 \
uvicorn app.embedding_server:app --host 127.0.0.1 --port 9000 --loop asyncio --http h11
```

### 3. 메인 백엔드 실행

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop asyncio --http h11
```

코드 변경을 자동 반영하려면 개발 중에만 `--reload`를 붙일 수 있습니다. 단, 로컬 임베딩 모델과 함께 쓸 때는 재로딩/프로세스 충돌이 생기면 서버를 완전히 껐다가 다시 켜는 편이 안전합니다.

### 4. 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:5173`으로 접속합니다.

## 환경 변수

- `OPENAI_API_KEY`: SQL 보조 생성, planner, RAG 답변 생성에 사용합니다.
- `LOCAL_EMBEDDING_MODEL`: 기본값은 `BAAI/bge-m3`입니다.
- `EMBEDDING_SERVER_URL`: 기본값은 `http://127.0.0.1:9000`입니다.
- `ENABLE_WEB_SEARCH`: `true`면 Tavily 기반 공식 홈페이지 검색을 사용합니다.
- `TAVILY_API_KEY`: 웹검색 사용 시 필요합니다.
- `WEB_SEARCH_DOMAINS`: 검색할 건국대학교 공식 도메인 목록입니다.

## 주요 API

- `POST /auth/login`
- `GET /students/me`
- `POST /chat`
- `GET /chat/progress/{request_id}`
- `GET /mcp/schema`
- `POST /mcp/query`

## 테스트 계정

- 학번: `202214001`부터 `202214100`
- 비밀번호: `password123`

## 테스트 질문 예시

```text
오늘 시간표 알려줘
컴퓨터공학과 교수목록 알려줘
데이터베이스 교수님 이메일 알려줘
계절학기로 알고리즘 수강하려 하는데, 전공 인정돼?
내가 앱 개발쪽에 관심이 생겼는데 수강할만한 과목 추천해줘
휴학 신청은 어떻게 해?
졸업 요건 보려면 어디서 확인해?
컴퓨터공학부 학부장 누구야?
이서준의 성적 알려줘
```
