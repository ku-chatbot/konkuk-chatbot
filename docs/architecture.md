# KU-Bot 구현 현황 정리

> 최종 업데이트: 2026-05-02
> 대상 브랜치: `feature/real-course-data`
>
> A–I 9개 개선 항목(라우터 정리 · LLM/룰 폴백 · 표 분기 · top_k 동결 · 청크 길이 가정 명시 · 인제스트 동결 · 테스트 도입 · 로그 의미화 · 교수 시드 정상화)을 적용한 직후 스냅샷입니다. 다이어그램·요구사항 분석서·유즈케이스를 다시 그리기 전 코드 기준 사실관계를 정리한 문서입니다.

---

## 1. 개요

KU-Bot은 자연어 질문을 두 가지 경로로 답변하는 학사정보 챗봇입니다.

- **DB 경로**: 학생 본인의 학사 데이터(수강·성적·시간표·등록금·교수·선수과목)에 대한 자연어 질문을 SQLite SELECT로 변환·실행해 답변.
- **참고문서 RAG 경로**: 휴학·복학·장학·졸업요건 등 학사정보 PDF를 Upstage Document Parser로 파싱·청킹한 뒤 KURE-v1 로컬 임베딩으로 FAISS 인덱스를 만들어 검색·답변.

단일 엔드포인트 `POST /chat`이 두 경로를 라우팅합니다.

---

## 2. 전체 구조

```
konkuk-chatbot/
├── backend/                 FastAPI · SQLite · 인증 · Text-to-SQL · RAG
│   ├── app/
│   │   ├── core/            설정·보안 (PBKDF2, 자체 JWT)
│   │   ├── db/              SQLAlchemy 엔진/세션, 시드
│   │   ├── models/          ORM 모델
│   │   ├── schemas/         Pydantic 요청/응답 (`display_format` 포함)
│   │   ├── routers/         FastAPI 라우터 (auth, students, chat, mcp)
│   │   ├── services/        비즈니스 로직 (분해된 6개 서비스)
│   │   └── scripts/         인제스트 배치
│   ├── tests/
│   │   ├── conftest.py      in-memory engine, db/student fixture
│   │   ├── unit/            sql_guard, text_to_sql, general_answer, summarizer
│   │   └── integration/     query_router, sql_executor, chat_service
│   ├── pytest.ini
│   ├── requirements.txt
│   ├── requirements-dev.txt pytest, freezegun, httpx
│   └── data/
│       ├── raw_documents/   원본 PDF + source_urls.txt 매니페스트
│       ├── parsed_documents/  Upstage 파싱 결과 (.md/.html/.json)
│       └── vector_index/    FAISS 인덱스 (.faiss/.npy/.ids.npy)
├── frontend/                React 19 + Vite 6 SPA
│   └── src/
│       ├── api/client.js    fetch 래퍼 + 토큰 관리
│       ├── pages/           LoginPage, ChatPage
│       └── components/      MessageBubble, RowTable
└── docs/                    architecture.md, plan.md
```

---

## 3. 백엔드 모듈 책임

### 3.1 라우터 (`app/routers/`)

| 라우터 | 경로 | 역할 |
|--------|------|------|
| `auth.py` | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | 로그인 토큰 발급, 자기 정보 |
| `students.py` | `GET /students/me` | 로그인 학생 프로필 |
| `chat.py` | `POST /chat` | 단일 채팅 진입점. `ChatService`에 위임 |
| `mcp.py` | `GET /mcp/schema`, `POST /mcp/query` | DB 스키마 노출 + 인증된 학생의 자유 SELECT |
| `deps.py` | — | `get_current_student` Bearer 인증 의존성 |

### 3.2 서비스 (`app/services/`) — 분해된 6개 클래스

```
ChatService (chat_service.py)
  ├─ GeneralAnswerService    (query_router.py)   날짜/시간 즉답
  ├─ QueryRouter             (query_router.py)   메시지 → "db" | "reference_rag"
  ├─ TextToSQLService        (text_to_sql.py)    LLM SQL 생성 + 키워드 fallback
  ├─ SqlExecutor             (sql_executor.py)   sql_guard 검증 + :student_id 강제 바인딩
  ├─ ResultSummarizer        (result_summarizer.py) rows → 표(2건↑) 또는 산문(LLM)
  └─ ReferenceRAGService     (reference_rag_service.py) FAISS 검색 + LLM 요약
```

보조 모듈:

| 모듈 | 책임 |
|------|------|
| `sql_guard.py` | SELECT 전용·다중문 차단·테이블 화이트리스트·`student_id = :student_id` 바인딩 강제·학번 리터럴 차단 |
| `openai_client.py` | OpenAI Responses/Chat/Embeddings 호환 래퍼. 키 미설정 시 `None` 반환 |
| `local_embedding.py` | `nlpai-lab/KURE-v1` sentence-transformers 임베딩 |
| `vector_store.py` | FAISS `IndexIDMap(IndexFlatIP)` 인덱스 저장/검색 |
| `document_ingestion.py` | PDF → Upstage 파싱 → 청크 → 임베딩 → FAISS 인덱스 빌드 |
| `document_parser.py` | Upstage 응답을 `ParsedChunk`로 정규화 (heading·page 보존) |
| `document_manifest.py` | `raw_documents/source_urls.txt` 파싱 (file/title/category/url) |
| `upstage_client.py` | Upstage Document Digitization API (sync + async fallback) |

### 3.3 데이터 모델 (`app/models/academic.py`)

| 테이블 | 핵심 컬럼 | 비고 |
|--------|----------|------|
| `student` | `student_id`(PK), `name`, `major`, `admission_year`, `status`, `hashed_password` | 인증 기준 |
| `professor` | `professor_id`, `name`, `email`, `office` | 시드는 `prof001@konkuk.ac.kr` / `공A301호` 패턴 (가짜) |
| `course` | `course_id`, `name`, `credit`, `room`, `description`, `professor_id` | 2026-1 실제 과목 13개 |
| `enrollment` | `enrollment_id`, `semester`, `grade`, `student_id`, `course_id` | 학기·성적 |
| `schedule` | `day_of_week`, `start_time`, `end_time`, `room`, `course_id` | 교시(`01-03`) 기반 |
| `tuition` | `semester`, `amount`, `payment_status`, `student_id` | 학기당 1행 |
| `prerequisite` | `course_id`, `pre_course_id` | 자기참조 |
| `query_log` | `student_id`, `message`, `route`, `generated_sql`, `success`, `error`, `created_at` | **§4.4 의미 체계 참조** |
| `reference_document` | `file_path`, `title`, `category`, `source_url`, `parsed_*_path`, `status` | 인제스트 메타 |
| `reference_chunk` | `document_id`, `chunk_index`, `content`, `page_start/end`, `heading`, `vector_id`, `token_count` | FAISS `vector_id`와 1:1 |

### 3.4 보안 (`app/core/security.py`)

- **비밀번호**: PBKDF2-HMAC-SHA256, 120,000 iterations, salt 16바이트.
- **토큰**: 자체 구현 JWT (HS256, `secret_key` 기반). 페이로드 `{sub, iat, exp, name}`. 대학 프로젝트 범위에서 의도된 선택.
- **인증 의존성**: `Bearer` 헤더 → `decode_access_token` → `Student` 로드.

---

## 4. 핵심 흐름

### 4.1 로그인

```
LoginPage.handleLogin
  → POST /auth/login {student_id, password}
  → auth.login: db.get(Student) → verify_password (PBKDF2) → create_access_token
  → 응답: {access_token, student}
프론트: localStorage["kubot_token"] = access_token
이후 모든 요청에 Authorization: Bearer <token>
```

`/auth/logout`은 메시지만 반환하고 서버 측 세션 무효화는 없음 → 클라이언트 토큰 삭제에만 의존. 대학 프로젝트 범위에서 수용.

### 4.2 채팅 (`POST /chat`)

```
프론트(ChatPage.send)
  → POST /chat {message}
  → chat.chat: get_current_student
  → ChatService.answer(db, student, message)
       1) GeneralAnswerService.try_answer
          - "오늘 며칠?", "지금 몇 시?" 등 키워드 매칭 → 즉답 (route="general")
       2) QueryRouter.classify(db, message)
          - 과목명 + DB 키워드 → "db"
          - REFERENCE 키워드 → "reference_rag"  (개인화 힌트 가드 제거됨, A 변경)
          - DB 키워드 → "db"
          - 그 외 → "reference_rag" (default)
       3) "db" 분기: ChatService._answer_from_db
          a) text_to_sql.generate_with_llm(message) → LLM SQL 후보
          b) text_to_sql.generate_with_rules(message) → 키워드 룰 SQL 후보
          c) 두 후보를 순서대로 시도:
             - validate_select_sql 거부 → errors에 기록 후 다음 후보
             - executor.execute 예외 → errors 기록 후 다음 후보
             - rows 있음 → ResultSummarizer.summarize → ChatResult(route="db")
             - rows 비었음 → 마지막 SQL 기억, 다음 후보로
          d) 모든 후보가 실행은 됐으나 빈 결과 → "조회 결과가 없습니다." 메시지
          e) 후보가 하나도 실행 못함 → DbAttempt(result=None) → RAG로 폴백
       4) "reference_rag" 분기 또는 DB 폴백 시:
          ReferenceRAGService.answer
            - local_embedding.embed(message) → FaissVectorStore.search(top_k=5)
            - vector_id로 ReferenceChunk + ReferenceDocument 로드
            - 청크 컨텍스트로 OpenAI Responses 호출, 출처 표기 강제
       5) QueryLog 기록 (§4.4 참조)
  ← ChatResponse {route, answer, display_format, sql?, rows[], sources[]}
```

### 4.3 결과 표시 형식 (C 변경)

`ResultSummarizer.summarize`가 행 수에 따라 분기:

| 행 수 | display_format | answer | LLM 호출 |
|-------|----------------|--------|----------|
| ≥ 2 | `"table"` | "조회 결과 N건입니다." 헤드라인 | ❌ (비용 0) |
| 1 | `"summary"` | LLM 산문 (실패 시 dict 직렬화) | ✅ |
| 0 | `"summary"` | "조회 결과가 없습니다." | ❌ |

프론트(`MessageBubble.jsx`):
- `displayFormat === 'table'` + `rows.length > 0` → `RowTable` 컴포넌트 렌더.
- 그 외 → `answer` 텍스트만.

`RowTable.jsx`의 `COLUMN_LABELS`가 영문 alias를 한국어 헤더로 매핑(`course_name → 과목`, `payment_status → 납부` 등). `amount`는 쉼표 + "원", `payment_status`는 "완납"/"미납"으로 셀 포맷팅.

### 4.4 `query_log` 의미 체계 (H 변경)

`success`는 **사용자에게 의미 있는 답변을 반환했는가**를 뜻합니다.

| 시나리오 | `route` | `success` | `error` | `generated_sql` |
|----------|---------|-----------|---------|----------------|
| 일반 질의(날짜/시간) | `general` | True | None | None |
| DB 답변 성공 (LLM 한 번에) | `db` | True | None | LLM SQL |
| DB 답변 성공 (LLM→룰 폴백) | `db` | True | `llm_sql_rejected_by_guard` 등 | 룰 SQL |
| DB 빈 결과 | `db_no_result` | **False** | `..._no_rows` | 마지막 SQL |
| RAG 1차 + 답변 | `reference_rag` | True (sources 있음) | None | None |
| RAG 1차 + 빈 검색 | `reference_rag` | **False** | `rag_no_sources` | None |
| DB 실패 후 RAG 폴백 | `reference_rag_after_db_failed` | sources 따라 | DB 단계 errors | 마지막 시도 SQL |

발표·시연용 통계 예시:
```sql
SELECT route, COUNT(*) FROM query_log GROUP BY route;
SELECT success, COUNT(*) FROM query_log GROUP BY success;
SELECT route, error, COUNT(*) FROM query_log
  WHERE error IS NOT NULL GROUP BY route, error;
```

`ChatResult.route`(사용자 응답)는 여전히 `general`/`db`/`reference_rag` 셋 중 하나만 노출. `_after_db_failed` 같은 메타는 로그에만 들어가 프론트 호환은 깨지지 않습니다.

### 4.5 문서 인제스트 (오프라인 배치)

```
python -m app.scripts.ingest_documents
  → create_tables
  → load_document_sources(source_urls.txt)
  → 각 PDF:
      upstage_document_parser.parse → JSON
      extract_markdown / extract_html / extract_chunks 저장
      ReferenceDocument upsert + ReferenceChunk 생성
      chunk.vector_id = chunk.id
      status = "ready"
  → _rebuild_vector_index
      ready 상태 chunk 전체를 KURE-v1로 임베딩
      FaissVectorStore.save → reference_chunks.{faiss,npy,ids.npy}
```

---

## 5. 시드 데이터 (`app/db/init_db.py`)

- **교수**: 과목 spec에서 추출한 이름들. email은 `prof{NNN}@konkuk.ac.kr`, office는 `공A{300+i}호` 패턴 (I 변경, 가짜 데이터 정책에 일관).
- **과목**: 2026-1학기 건국대 종합강의시간표 기반 13개. 시간표는 "목04-06(공A1510)" 형식 문자열을 파싱.
- **선수과목**: 7쌍 하드코딩 (예: `알고리즘 ← 자료구조`).
- **학생**: 학번 `202214001`–`202214100` 100명. `password123`. 학과/입학년도 결정적 분배.
- **수강**: 학생당 5과목 무작위 (`Random(42)`).
- **등록금**: 학생당 1행, 금액 `3,980,000`–`4,340,000`, `payment_status`는 3의 배수만 미납.

> 시드 가드: `if db.query(Student).first(): return` 때문에 모델 변경 시 자동 마이그레이션 안 됨. **SQLite 파일 삭제 후 재구동이 사실상의 마이그레이션 절차.** I 변경(교수 시드)을 반영하려면 `kubot.db`를 지우고 재기동.

---

## 6. 프론트엔드 구조

| 파일 | 역할 |
|------|------|
| `main.jsx` | React 엔트리 |
| `App.jsx` | 토큰 유무로 `LoginPage`/`ChatPage` 토글, `/students/me`로 자동 로그인 |
| `pages/LoginPage.jsx` | 학번/비밀번호 입력 |
| `pages/ChatPage.jsx` | 사이드바(예시 버튼·로그아웃)·메시지 리스트·입력창. `POST /chat` 호출. `display_format`/`rows`를 메시지 상태에 보관 |
| `components/MessageBubble.jsx` | 메시지 + route/sql/sources 메타 + 표 분기 |
| `components/RowTable.jsx` | `display_format === 'table'`일 때 렌더. 컬럼 라벨/셀 포맷 매핑 |
| `api/client.js` | `fetch` 래퍼, `localStorage["kubot_token"]` |
| `styles.css` | 전역 스타일 + `.row-table-wrap`/`.row-table` |

상태 관리는 `useState`만 사용. 라우팅 라이브러리 없음.

---

## 7. 외부 의존성

### 7.1 OpenAI

- **모델**: `gpt-4.1-mini` (Responses API 우선, Chat Completions 폴백).
- **임베딩**: `text-embedding-3-small` — 코드 경로에 남아 있으나 현재 사용처는 거의 없음 (RAG는 KURE-v1을 사용). `openai_service.embed`만 정의되어 있음.
- **사용처**:
  - `TextToSQLService._sql_with_openai` — 자연어 → SQL JSON.
  - `ResultSummarizer._llm_summary` — 단건 행 → 자연어 (다건은 LLM 호출 안 함).
  - `ReferenceRAGService.answer` — RAG 답변 합성.
- 키 미설정 시 모두 `None`을 반환해 fallback 경로로 흐릅니다. 테스트 환경에서는 `OPENAI_API_KEY=""`를 강제해 결정론을 확보합니다.

### 7.2 Upstage Document Parse

- 인제스트 단계에서만 사용 (런타임 챗에서는 호출 안 함).
- sync 실패 시 async 폴백 (request_id 폴링).

### 7.3 KURE-v1 (`nlpai-lab/KURE-v1`)

- 한국어 sentence-transformers, CPU 추론.
- 인제스트와 런타임 RAG 검색 양쪽에서 사용. 첫 호출 시 모델 로드 비용 큼.

---

## 8. 보안 현황

✅ **이미 강화된 항목**

- `sql_guard`가 `student/enrollment/tuition` 테이블 사용 시 `WHERE ... student_id = :student_id` 바인딩 등장을 강제.
- 학번 리터럴(`= 202214001`, `IN (1,2,3)` 등) 정규식으로 거부.
- `_fallback_sql`의 모든 LIKE 패턴을 `:course_pattern` 바인딩으로 교체 (f-string SQL 인젝션 제거).
- `SqlExecutor.execute`가 항상 `student_id`를 `current_student.student_id`로 강제 주입 (호출자가 임의로 넣어도 덮어씀).
- LLM 프롬프트에도 "학번 리터럴 금지·`:student_id` 바인딩 사용" 규칙 명시.
- `sql_guard` 단위 테스트 21개로 회귀 방어.

✅ **대학 프로젝트 범위에서 수용된 결정** (논의·승인 완료)

| 항목 | 결정 |
|------|------|
| 자체 JWT 구현 | 라이브러리 교체 없이 현재 코드 유지 |
| `secret_key` 기본값 | `.env`에서 덮어쓰는 운영 절차로 충분 |
| `/auth/logout` no-op | 토큰 만료(120분)까지 클라이언트 삭제로 운영 |
| `/mcp/query` 자유 SELECT | `course`/`professor`/`prerequisite`는 공개 정보로 간주 |
| `ResultSummarizer`가 row를 LLM에 송신 | 시드가 모두 가짜 데이터이므로 정책상 무관 |
| CORS `192.168.*` 광역 허용 | 사내/테스트 환경 전용 |
| 비밀번호 정책 (모두 `password123`) | 데모 계정만 운영 |

운영 전환 시 재검토 필요한 항목으로만 표시.

---

## 9. 성능·운영 현황

| 항목 | 현재 상태 | 비고 |
|------|----------|------|
| DB | SQLite 단일 파일 (`./kubot.db`) | 동시성 한계 있음 |
| FAISS 인덱스 | `IndexFlatIP`, 디스크 영속 | 청크 수가 작아 충분 |
| 임베딩 모델 로드 | `LocalEmbeddingService.model`은 `cached_property` → 첫 요청 시 1회 로드 | 콜드 스타트 수 초 |
| LLM 호출 횟수 | DB 다건 응답: 0회 (표 분기). DB 단건 응답: 1회. RAG 응답: 1회. 둘 다 SQL 생성은 LLM 1회 추가 가능 | C 변경으로 DB 다건 케이스 비용 0 |
| Course 이름 조회 | `QueryRouter.classify`가 매 요청마다 `course.name` 전부 조회 | 13행이라 비용 미미 |
| 로그 | `query_log`에 의미 있는 success/error 기록 (§4.4) | 시연 통계 가능 |
| 테스트 | 69개 (단위 + 통합), pytest로 5초 내 실행 | G-B 범위 |
| CI/CD | 없음 | 로컬 실행만 |
| 관측성 | `print` 로그 + `query_log` 테이블 | 구조화 로깅·메트릭 없음 |

### 9.1 RAG 검색 파라미터 (D 동결)

- `top_k=5`, `extract_chunks(max_chars=1800)`, `_embedding_text(max_chars=2500)` 유지.
- 인덱스 규모가 작아 MMR/카테고리 분산 도입은 학기 후반 답변 다양성 신호 발생 시점까지 보류.
- **가정 명시 (E)**: `extract_chunks.max_chars`(1800)는 `document_ingestion._embedding_text.max_chars`(2500)보다 작아야 검색 임베딩과 LLM 컨텍스트가 일치합니다. 두 함수 docstring에 주석으로 박아둠.

### 9.2 인제스트 (F 동결)

- 현재는 `status == "ready"`이면 재파싱 스킵, FAISS는 매번 전체 재빌드.
- 데모용으론 충분. 증분 빌드(파일 해시 비교 + 부분 갱신)는 학기 말 시연 부담 시 도입.

---

## 10. 코드 품질·일관성 현황

✅ **잘 정리된 점**

- 서비스 분해(`ChatService`/`QueryRouter`/`TextToSQLService`/`SqlExecutor`/`ResultSummarizer`/`ReferenceRAGService`)가 계획서 클래스 다이어그램과 1:1 매핑됨.
- RAG가 `ReferenceRAGService`로 일원화 → 죽은 코드 경로(`AcademicDocument`+`rag_service`) 제거.
- 응답 스키마 `ChatResponse`가 두 경로에서 동일 (`route`, `answer`, `display_format`, `sql?`, `rows`, `sources`).
- DB 트랜잭션은 `get_db` 의존성으로 일관적으로 닫힘.
- LLM 후보가 가드/실행에서 거부되면 룰 fallback이 자동으로 시도됨 (B 변경).
- `ResultSummarizer`가 다건/단건을 자동 분기해 LLM 비용을 절약 (C 변경).
- `query_log`에 실패 사유가 누적되어 시연 통계로 활용 가능 (H 변경).

⚠️ **여전히 남은 개선 여지** (시연 후 또는 시간 여유 시)

| 영역 | 현재 | 제안 |
|------|------|------|
| `mcp.py` 스키마 | 라우터에 하드코딩된 dict | 모델 메타에서 자동 생성 가능 |
| 인제스트 멱등성 (F) | `status == "ready"` 시 스킵하지만 FAISS 매번 재빌드 | 해시 기반 변경 감지 + 부분 갱신 |
| 프론트 라우팅 | 단일 컴포넌트에서 토글 | react-router로 분리 (확장 시) |
| 프론트 상태 | `useState`만 사용, 메시지 영구 저장 없음 | 새로고침 시 대화 유실 |
| RAG 다양성 (D) | top_k=5, MMR 없음 | 답변 다양성 모니터링 후 MMR 검토 |

---

## 11. 알려진 결함·주의사항

1. **Schedule 파싱 형식이 한정적**.
   `_parse_room_text`는 "월04-06(공A1510)" 같은 패턴만 처리. 변형 입력에 약함.
2. **`QueryRouter`의 `course.name in message` 매칭이 부분 문자열**.
   짧은 과목명이 다른 단어 안에 들어가면 false positive 가능. 현재 시드 13개 과목명은 모두 충분히 길어서 안전하지만, 향후 짧은 교양명 추가 시 주의.
3. **`ReferenceRAGService.answer`가 빈 RAG 결과 시 "ingestion 했는지 확인하세요" 답변 노출**.
   사용자에게는 운영 디테일이 새어나가는 메시지. UX 다듬기 필요.
4. **`ResultSummarizer._llm_summary` 폴백이 dict를 그대로 직렬화**.
   한국어 답변과 톤이 어긋남. 단건 케이스에 한해 발생.
5. **시드 가드** 때문에 모델 변경 시 자동 마이그레이션 안 됨.
   현재 SQLite 파일 삭제 후 재구동이 사실상의 마이그레이션 절차.
6. **`parsed_documents/` 디렉토리에 일부 문서만 파싱**.
   `source_urls.txt`에 5개 PDF 등록, 모두 파싱 완료. 큰 문서가 인제스트 시 비용·시간이 큼.

---

## 12. 다음 단계

### 단기 — 다이어그램·요구사항서 작성
1. **시퀀스 다이어그램 3종**
   - 로그인
   - `/chat` DB 분기 (LLM→룰 폴백 포함)
   - `/chat` RAG 분기 (1차 + DB 폴백 후)
2. **클래스 다이어그램** — 분해된 서비스 6개 + 모델 + DTO (`ChatResult`/`DbAttempt`/`Summary`)
3. **유즈케이스 다이어그램** — 학생 행위자 + 8개 시나리오 (예시 버튼 기준)
4. **요구사항 분석서** — 보안 요구사항을 §8 현재 가드 규칙과 일치하게 갱신

### 중기 — 시연 품질
5. **OpenAI 응답 캐싱** — 동일 질의 SQL 생성/요약 캐시 (TTL 기반). 시연 반복 시 효과 큼.
6. **빈 RAG 메시지 다듬기** — 운영 디테일 제거, 사용자 친화 메시지로.

### 장기 — 시간 여유 시 (현재 보류)
7. **RAG MMR/카테고리 분산** — 답변 다양성 신호 시.
8. **인제스트 증분화** — 파일 해시 비교 + FAISS 부분 갱신.
9. **DB 마이그레이션 도구** — Alembic.
10. **프론트 대화 영속성** — IndexedDB 또는 백엔드 히스토리 API.
11. **관측성** — 구조화 로그, 라우트별 응답시간, OpenAI 비용 집계.
12. **CI** — GitHub Actions에서 pytest 자동 실행.

---

## 13. 합의된 설계 원칙 (이 문서를 미래의 자기 자신에게)

- **단일 엔드포인트 `POST /chat`**. `/chat-v2` 같은 분기 라우터는 만들지 않는다.
- **`ChatService`는 조율자**. 비즈니스 로직(분류·SQL 생성·실행·요약·RAG)은 각 서비스에 둔다.
- **`student_id`는 `SqlExecutor`가 강제 주입**. 호출자(상위 서비스나 라우터)가 직접 `student_id`를 SQL 파라미터에 넣지 않는다.
- **RAG는 `ReferenceRAGService` 한 곳**. 새 문서 종류는 `ReferenceDocument.category`로 구분한다.
- **민감 가드는 다중 방어**. LLM 프롬프트(요청)·`sql_guard`(검증)·`SqlExecutor` 강제 바인딩(실행) 세 단계로 막는다.
- **라우팅 default는 RAG**. DB 키워드에 명확히 걸리지 않으면 학사정보 문서를 본다 (A 합의).
- **DB 분기는 두 후보(LLM, 룰)를 순서대로 시도**. LLM이 가드 거부되거나 실행 실패해도 룰이 살아 있으면 답변한다 (B 합의).
- **결과 표시 형식은 행 수가 결정**. 2건 이상은 표(LLM 호출 없음), 단건은 산문 LLM (C 합의).
- **`query_log.success`는 사용자에게 의미 있는 답변을 했는가**. 빈 결과/거부/예외는 모두 success=False, error에 사유 누적 (H 합의).
- **테스트 추가 비용 < 회귀 손실**. `sql_guard`/라우팅/`ChatService` 분기는 신규 변경 시 반드시 테스트 동반 (G 합의).
- **시드 데이터는 가짜이지만 일관**. placeholder 문자열 대신 실제 값처럼 보이는 패턴을 쓴다 (I 합의).
- **문서는 코드 변경과 함께 업데이트**. 이 문서가 그 사례.
