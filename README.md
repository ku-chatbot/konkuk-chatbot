# KU-Bot

자연어 질문을 내부 학사 DB 또는 학사정보 문서 검색으로 답변하는 건국대학교 학사정보 챗봇 프로토타입입니다.

## 구조

```text
backend/   FastAPI · SQLite · 인증 · Text-to-SQL · 학사정보 RAG · pytest
frontend/  React 19 + Vite 6 · 로그인 화면 · 챗봇 UI (표/산문 자동 분기)
docs/      구현 현황·계획·다이어그램·요구사항 분석서
참고자료/  원본 참고자료 보관
```

## 답변 흐름

1. 사용자가 로그인합니다.
2. 단일 엔드포인트 `POST /chat`이 메시지를 받아 `ChatService`가 라우팅합니다.
3. 날짜·시간 즉답이 가능한 질문은 `general` 분기로 즉답합니다.
4. 수강·성적·시간표·등록금·교수·선수과목 같은 DB 기반 질문은 LLM과 키워드 룰 두 후보 SQL을 순서대로 시도합니다. 가드 거부·실행 예외·빈 결과는 `query_log`에 누적됩니다.
5. 휴학·복학·장학·졸업요건처럼 일반 학사정보 질문이면 KURE-v1 임베딩 + FAISS로 학사 문서 청크를 검색해 LLM이 출처와 함께 답변합니다.
6. 모든 DB 조회는 `SqlExecutor`가 인증된 `student_id`를 강제 주입해 본인 데이터로만 제한합니다.

## 실행

백엔드:

```bash
cd backend
python3 -m venv .venv          # 또는 conda create -n kubot python=3.11
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

`backend/.env`의 `OPENAI_API_KEY`를 입력하면 OpenAI Responses API로 Text-to-SQL과 자연어 답변을 생성합니다. 키가 없어도 키워드 fallback SQL과 RAG 검색만으로 기본 데모는 동작합니다.

## 참고문서 인제스트

```bash
cd backend
python -m app.scripts.ingest_documents
```

`data/raw_documents/`의 PDF를 Upstage Document Parser로 파싱하고 `data/parsed_documents/`에 저장한 뒤 KURE-v1 임베딩으로 FAISS 인덱스를 빌드합니다. 이미 파싱된 문서가 포함되어 있어 RAG는 키 없이도 동작합니다.

## 테스트

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

`sql_guard`, 라우팅, `ChatService` 분기, 결과 표시 형식, query_log 의미 체계까지 약 69개 단위·통합 테스트가 5초 내에 실행됩니다. OpenAI 키는 `conftest.py`가 빈 값으로 강제하므로 실제 API 호출 없이 결정론적으로 동작합니다.

## 테스트 계정

- 학번: `202214001`부터 `202214100`
- 비밀번호: `password123`

## 문서

이번 학기 갱신본은 `docs/` 아래에 있습니다.

| 문서 | 내용 |
|------|------|
| [`docs/architecture.md`](docs/architecture.md) | 코드 기준 구현 현황·흐름·결함·백로그·설계 원칙 |
| [`docs/plan.md`](docs/plan.md) | 학기 개발 계획서 (지난 학기 결과 + 이번 학기 진행 상황) |
| [`docs/requirements.md`](docs/requirements.md) | 요구사항 분석서 (FR · NFR · 시나리오 수용 기준) |
| [`docs/usecase.md`](docs/usecase.md) | 유즈케이스 다이어그램 + 서술서 (Mermaid) |
| [`docs/class.md`](docs/class.md) | 클래스 다이어그램 4종 — 서비스, 보조 모듈, ORM, 라우터 (Mermaid) |
| [`docs/sequence.md`](docs/sequence.md) | 시퀀스 다이어그램 7종 — 로그인, DB 성공/폴백/빈 결과, RAG, 인제스트 (Mermaid, 파라미터·반환값 명시) |
| [`docs/legacy/`](docs/legacy/) | 지난 학기 PDF/XLSX 보관함 (현재 구현과 불일치 가능) |
