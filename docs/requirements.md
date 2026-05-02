# 요구사항 분석서

> 최종 업데이트: 2026-05-02
> 대상: KU-Bot (학생 전용 학사정보 챗봇)
>
> 본 문서는 코드 기준 현재 구현(브랜치 `feature/real-course-data`, A–I 9개 개선 항목 적용 후)과 일치하도록 작성되었습니다. 구조·흐름의 상세는 [`architecture.md`](./architecture.md), 클래스/시퀀스/유즈케이스는 각각 [`class.md`](./class.md), [`sequence.md`](./sequence.md), [`usecase.md`](./usecase.md)를 참고합니다.

---

## 1. 시스템 개요

| 항목 | 내용 |
|------|------|
| 시스템명 | KU-Bot (건국대 학사정보 챗봇 프로토타입) |
| 사용자 | 건국대학교 학생 (시연용 모의 학번 100명) |
| 핵심 가치 | 메뉴 탐색 없이 자연어로 본인 학사정보(DB) 또는 학사 안내 문서(RAG)를 조회 |
| 운영 환경 | 로컬/사내 데모. 운영 배포 아님 |
| 데이터 정책 | 모든 시드는 가짜 데이터. 실제 학적·성적·등록금 데이터 미사용 |

---

## 2. 행위자

| 행위자 | 역할 |
|--------|------|
| **학생** | 로그인 후 자연어로 질문 |
| **OpenAI** | Text-to-SQL, 자연어 답변 합성, RAG 답변 합성 |
| **Upstage Document Parse** | 인제스트 단계 PDF 파싱 (런타임 호출 없음) |
| **관리자** | 오프라인 인제스트 스크립트 실행 |

---

## 3. 기능 요구사항

### 3.1 인증 (FR-AUTH)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-AUTH-1 | 학번/비밀번호로 로그인 | `routers/auth.py:login` | 수동 |
| FR-AUTH-2 | PBKDF2-SHA256 120k iter로 비밀번호 해싱 | `core/security.py:hash_password` | 수동 |
| FR-AUTH-3 | 자체 JWT(HS256) 발급, exp 120분 | `core/security.py:create_access_token` | 수동 |
| FR-AUTH-4 | 모든 챗 API는 `Authorization: Bearer` 검증 | `routers/deps.py:get_current_student` | 수동 |
| FR-AUTH-5 | 토큰 만료/없음 → 401 | 동상 | 수동 |
| FR-AUTH-6 | 로그아웃 (클라이언트 측 토큰 폐기) | `routers/auth.py:logout` + 프론트 | 수동 |

### 3.2 채팅 진입점 (FR-CHAT)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-CHAT-1 | 단일 엔드포인트 `POST /chat` | `routers/chat.py` | `tests/integration/test_chat_service.py` |
| FR-CHAT-2 | 인증된 학생 기준으로만 응답 | `chat_router` + `deps` | 통합 |
| FR-CHAT-3 | 응답 스키마: `{route, answer, display_format, sql?, rows[], sources[]}` | `schemas/chat.py:ChatResponse` | 자동 |

### 3.3 라우팅 (FR-ROUTE)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-ROUTE-1 | 날짜·시간 키워드 → `general` 즉답 (DB/LLM 호출 없음) | `query_router.GeneralAnswerService` | `test_general_answer.py` 5건 |
| FR-ROUTE-2 | 과목명 + DB 키워드 → `db` | `QueryRouter.classify` 1번 분기 | `test_query_router.py` |
| FR-ROUTE-3 | 참고문서 키워드 → `reference_rag` | 2번 분기 | 동상 |
| FR-ROUTE-4 | DB 키워드만 → `db` | 3번 분기 | 동상 |
| FR-ROUTE-5 | 그 외 → `reference_rag` (default) | 4번 분기 | 동상 |
| FR-ROUTE-6 | "교수" 단독은 DB로 가지 않음 (과목명과 함께 와야 DB) | A 변경 | `test_query_router.py:test_professor_keyword_alone_no_longer_forces_db` |
| FR-ROUTE-7 | "내" 등 1인칭이 RAG 키워드(예: "내 휴학")를 가로채지 않음 | A 변경 (PERSONAL_HINTS 제거) | `test_query_router.py:test_personal_with_reference_keyword_routes_to_rag` |

### 3.4 Text-to-SQL (FR-T2S)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-T2S-1 | LLM 후보(`generate_with_llm`) 생성 시 스키마/규칙 프롬프트 동봉 | `text_to_sql.py:_sql_with_openai` | 수동 |
| FR-T2S-2 | LLM 실패 시 키워드 룰(`generate_with_rules`) 후보 생성 | `_fallback_sql` | `test_text_to_sql.py` 14건 |
| FR-T2S-3 | LLM 후보가 가드/실행에서 거부되면 룰 후보 자동 시도 | `chat_service._answer_from_db` (B 변경) | `test_chat_service.py:test_llm_invalid_sql_falls_back_to_rule` |
| FR-T2S-4 | 두 후보 모두 빈 결과면 "조회 결과가 없습니다…" 안내 | 동상 | `test_chat_service.py:test_db_no_rows_returns_friendly_message` |
| FR-T2S-5 | 두 후보 모두 실행 못 하면 RAG로 폴백 | 동상 | 통합 |
| FR-T2S-6 | 사용자 입력 과목명은 LIKE 바인딩(`:course_pattern`)으로만 SQL에 들어감 | `_fallback_sql` | `test_sql_executor.py:test_executor_passes_named_params` |

### 3.5 SQL 실행·검증 (FR-SQL)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-SQL-1 | SELECT 외 명령 거부 | `sql_guard` | `test_sql_guard.py` |
| FR-SQL-2 | 다중문(`;`) 거부 | 동상 | 동상 |
| FR-SQL-3 | 화이트리스트 외 테이블 참조 거부 | 동상 | 동상 |
| FR-SQL-4 | `student/enrollment/tuition` 사용 시 `student_id = :student_id` 등장 강제 | 동상 | 동상 |
| FR-SQL-5 | 학번 리터럴(`= 숫자`, `IN (..)`) 거부 | 동상 | 동상 |
| FR-SQL-6 | `:student_id`는 `SqlExecutor`가 강제 주입, 호출자 임의 주입 불허 | `sql_executor.py` | `test_sql_executor.py:test_executor_overrides_caller_supplied_student_id` |

### 3.6 결과 표시 형식 (FR-DISP)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-DISP-1 | 행 수 ≥ 2 → `display_format="table"`, "조회 결과 N건입니다." 헤드라인 | `result_summarizer.py` | `test_result_summarizer.py` |
| FR-DISP-2 | 단건 → `display_format="summary"`, LLM 산문 (실패 시 dict 폴백) | 동상 | 동상 |
| FR-DISP-3 | 0건 → `summary` + "조회 결과가 없습니다." | 동상 | 동상 |
| FR-DISP-4 | 프론트는 `displayFormat==='table'`이면 `RowTable` 컴포넌트로 렌더 | `MessageBubble.jsx` + `RowTable.jsx` | 수동 |
| FR-DISP-5 | 컬럼 라벨 영→한 매핑은 프론트에서 (`COLUMN_LABELS`) | `RowTable.jsx` | 수동 |
| FR-DISP-6 | `amount` 셀은 천단위 쉼표 + "원", `payment_status`는 "완납"/"미납" | 동상 | 수동 |

### 3.7 RAG (FR-RAG)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-RAG-1 | 메시지를 KURE-v1로 임베딩 후 FAISS top_k=5 검색 | `reference_rag_service._retrieve` | 수동 |
| FR-RAG-2 | `ReferenceDocument.status == "ready"`인 청크만 검색 대상 | 동상 | 수동 |
| FR-RAG-3 | LLM에 청크 컨텍스트 전달, 출처(제목/페이지/URL) 표기 강제 | `reference_rag_service.answer` | 수동 |
| FR-RAG-4 | 검색 결과 없으면 "관련 내용을 찾지 못했습니다" 안내 | 동상 | 수동 |

### 3.8 인제스트 (FR-ING)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-ING-1 | `source_urls.txt` 매니페스트로 file/title/category/url 관리 | `document_manifest.py` | 수동 |
| FR-ING-2 | Upstage Document Parser 호출 (sync, 실패 시 async 폴백) | `upstage_client.py` | 수동 |
| FR-ING-3 | 파싱 결과를 `data/parsed_documents/{stem}.{json,md,html}`로 보존 | `document_ingestion.py` | 수동 |
| FR-ING-4 | 청크 분할: `extract_chunks(max_chars=1800)`, heading/page 보존 | `document_parser.py` | 수동 |
| FR-ING-5 | KURE-v1 임베딩 → FAISS `IndexIDMap(IndexFlatIP)`로 디스크 영속 | `vector_store.py` | 수동 |
| FR-ING-6 | `status == "ready"`이면 재파싱 스킵 (멱등) | `document_ingestion._ingest_one` | 수동 |

### 3.9 운영 가시성 — `query_log` (FR-LOG)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-LOG-1 | 모든 응답을 1행으로 기록 | `chat_service._log` | `test_chat_service.py` 6건 |
| FR-LOG-2 | `route` 값: `general`/`db`/`db_no_result`/`reference_rag`/`reference_rag_after_db_failed` | 동상 | 동상 |
| FR-LOG-3 | `success`: 사용자에게 의미 있는 답변 여부 | 동상 | 동상 |
| FR-LOG-4 | `error`: 실패 사유 누적 (예: `llm_sql_rejected_by_guard`) | 동상 | 동상 |
| FR-LOG-5 | `generated_sql`: 마지막으로 시도/실행한 SQL | 동상 | 동상 |
| FR-LOG-6 | 사용자 응답의 `route`는 `general`/`db`/`reference_rag` 셋만 노출 (메타 라우트는 로그 전용) | 동상 | 동상 |

### 3.10 MCP 보조 API (FR-MCP)

| ID | 요구사항 | 구현 위치 | 검증 |
|----|----------|----------|------|
| FR-MCP-1 | `GET /mcp/schema` — 화이트리스트 테이블/컬럼 노출 | `routers/mcp.py` | 수동 |
| FR-MCP-2 | `POST /mcp/query` — 인증된 학생이 자유 SELECT 실행 (가드 통과 한정) | 동상 | 수동 |

---

## 4. 비기능 요구사항

### 4.1 보안 (NFR-SEC)

| ID | 요구사항 | 만족 여부 |
|----|----------|----------|
| NFR-SEC-1 | 비밀번호는 평문 저장 금지 (PBKDF2 + salt) | ✅ |
| NFR-SEC-2 | 세션은 토큰 기반, 만료 시간 설정 (120분) | ✅ |
| NFR-SEC-3 | 모든 쿼리는 인증된 학생 ID로만 데이터 조회 | ✅ |
| NFR-SEC-4 | SQL 인젝션 방지: 파라미터 바인딩 강제, 학번 리터럴 차단 | ✅ |
| NFR-SEC-5 | SELECT 외 명령 차단 | ✅ |
| NFR-SEC-6 | 응답에 다른 학생 데이터 노출 금지 | ✅ (`SqlExecutor`가 student_id 강제 덮어쓰기) |

### 4.2 성능 (NFR-PERF)

| ID | 요구사항 | 만족 여부 |
|----|----------|----------|
| NFR-PERF-1 | DB 다건 응답은 LLM 호출 0회 | ✅ (C 변경) |
| NFR-PERF-2 | DB 단건 응답은 LLM 호출 1회 | ✅ |
| NFR-PERF-3 | RAG 응답은 LLM 호출 1회 + 임베딩 1회 | ✅ |
| NFR-PERF-4 | 자동화 테스트 전체 5초 이내 실행 | ✅ (69개, 실측 5초) |

### 4.3 신뢰성 (NFR-REL)

| ID | 요구사항 | 만족 여부 |
|----|----------|----------|
| NFR-REL-1 | LLM/외부 API 키 없이도 시스템이 동작 (자연 폴백) | ✅ (`openai_service`가 None 반환) |
| NFR-REL-2 | LLM SQL이 거부되어도 룰 fallback로 답변 시도 | ✅ (B 변경) |
| NFR-REL-3 | DB 분기가 모두 실패해도 RAG로 사용자 응답 보장 | ✅ |
| NFR-REL-4 | 빈 결과/실패 사유는 `query_log`에 기록 | ✅ (H 변경) |

### 4.4 유지보수성 (NFR-MAINT)

| ID | 요구사항 | 만족 여부 |
|----|----------|----------|
| NFR-MAINT-1 | 서비스가 단일 책임으로 분해됨 | ✅ (6개 클래스) |
| NFR-MAINT-2 | 각 분기에 자동화 테스트 동반 | ✅ (69개) |
| NFR-MAINT-3 | 코드 변경과 함께 문서 갱신 | ✅ (architecture/plan/diagrams) |
| NFR-MAINT-4 | 응답 스키마는 두 경로에서 동일 | ✅ (`ChatResponse`) |

### 4.5 사용성 (NFR-USAB)

| ID | 요구사항 | 만족 여부 |
|----|----------|----------|
| NFR-USAB-1 | 결과는 행 수에 따라 표/산문 자동 분기 | ✅ |
| NFR-USAB-2 | 다건 응답 표는 한국어 컬럼 라벨 | ✅ (`COLUMN_LABELS`) |
| NFR-USAB-3 | 금액·납부 상태는 한국식 포맷 | ✅ (쉼표 + "원" / "완납"·"미납") |
| NFR-USAB-4 | RAG 답변에는 출처(문서 제목·페이지·URL) 표기 | ✅ |
| NFR-USAB-5 | 응답에 라우트 메타 표시 (`내부 DB` / `학사정보`) | ✅ (`MessageBubble`) |
| NFR-USAB-6 | 실행 SQL을 `<details>`로 접어 표시 (디버그 용도) | ✅ |

---

## 5. 제약사항 및 가정

### 5.1 운영 환경 가정

- **데이터**: 모든 시드는 가짜. 실제 학적/성적/등록금 데이터 없음.
- **사용자**: 학생 100명 모두 비밀번호 `password123`. 데모 전용.
- **DB**: SQLite 단일 파일. 다중 사용자 동시 쓰기 한계 있음.
- **외부 API 비용**: OpenAI/Upstage 호출은 개인 키 한도 내에서 운영.

### 5.2 대학 프로젝트 범위에서 수용된 결정

| 항목 | 운영 환경에서는 재검토 필요 |
|------|---------------------------|
| 자체 JWT (HS256) | ✅ 라이브러리 검증 미수행 |
| `secret_key` 기본값 (`change-this-secret`) | ✅ `.env`로 덮어쓰는 운영 절차로 충분 |
| `/auth/logout` no-op | ✅ 토큰 폐기 메커니즘 없음 |
| `/mcp/query` 자유 SELECT | ✅ `course`/`professor`/`prerequisite`는 공개 정보로 간주 |
| `ResultSummarizer`가 row를 LLM에 송신 | ✅ 가짜 데이터이므로 정책상 무관 |
| CORS `192.168.*` 광역 허용 | ✅ 사내/테스트 환경 전용 |
| 비밀번호 정책 (모두 `password123`) | ✅ 데모 계정만 운영 |

### 5.3 임베딩 길이 가정

`extract_chunks(max_chars=1800) < _embedding_text(max_chars=2500)` — 검색 임베딩과 LLM 컨텍스트가 일치하려면 두 상수 관계가 유지되어야 함. 두 함수에 주석으로 명시됨 (E 변경).

### 5.4 인제스트 가정

- Upstage API 키가 있어야 새 PDF 인제스트 가능. 키 없어도 이미 파싱된 인덱스로 RAG는 동작.
- FAISS 인덱스는 매 인제스트마다 전체 재빌드 (증분 빌드 미지원, F 동결).

---

## 6. 시나리오별 수용 기준

| 시나리오 | 입력 | 기대 결과 | 검증 |
|---------|------|----------|------|
| S-1 | "내 수강 과목 알려줘" | route="db", display_format="table", rows≥2, "조회 결과 N건입니다." | 통합 |
| S-2 | "내 성적 보여줘" | route="db", display_format="table", rows≥2 | 통합 |
| S-3 | "오늘 시간표 알려줘" | route="db", display_format="table" | 통합 |
| S-4 | "데이터베이스 교수님 이메일 알려줘" | route="db", course_pattern="%데이터베이스%" 바인딩 | 통합 |
| S-5 | "이번 학기 등록금 얼마야?" | route="db", display_format="summary", rows=1 | 통합 |
| S-6 | "운영체제 선수과목 알려줘" | route="db", display_format에 따라 분기 | 통합 |
| S-7 | "휴학 신청은 어떻게 해?" | route="reference_rag", sources 비어있지 않음 | 통합 |
| S-8 | "졸업 요건 알려줘" | route="reference_rag" | 통합 |
| S-9 | "내 휴학 어떻게 신청해?" | route="reference_rag" (1인칭에 가려지지 않음) | `test_query_router.py` |
| S-10 | "교수 임용 절차 알려줘" | route="reference_rag" ("교수" 단독은 DB 아님) | `test_query_router.py` |
| S-11 | "오늘 며칠?" | route="general", DB/LLM 호출 없음 | `test_general_answer.py` |
| S-12 | LLM이 학번 리터럴 SQL 반환 | 가드 거부 → 룰 fallback로 답변 → log.error에 사유 누적 | `test_chat_service.py` |
| S-13 | DB 키워드인데 룰 매칭 없음, LLM도 None | RAG 폴백 (route 메타: `_after_db_failed`) | `test_chat_service.py` |
| S-14 | DB SQL이 빈 결과 | "조회 결과가 없습니다…" + log route="db_no_result" | `test_chat_service.py` |
| S-15 | 토큰 없이 호출 | 401 | 수동 |
| S-16 | 만료된 토큰 | 401 | 수동 |

---

## 7. 미충족·보류 항목

| ID | 항목 | 상태 | 비고 |
|----|------|------|------|
| OUT-1 | RAG MMR / 카테고리 분산 | 보류 (D) | 답변 다양성 신호 시 |
| OUT-2 | 인제스트 증분 빌드 | 보류 (F) | 학기 후반 시연 부담 시 |
| OUT-3 | OpenAI 응답 캐싱 | 미구현 | 시연 반복 시 효과 큼 |
| OUT-4 | RAG 빈 결과 메시지 UX 다듬기 | 미구현 | "ingestion 했는지 확인하세요" 노출 |
| OUT-5 | 프론트 대화 영속성 | 미구현 | 새로고침 시 대화 유실 |
| OUT-6 | DB 마이그레이션 도구 (Alembic) | 미구현 | 모델 변경 시 SQLite 파일 삭제 |
| OUT-7 | CI (GitHub Actions) | 미구현 | 로컬 pytest만 |

---

## 8. 변경 이력

| 일자 | 변경 |
|------|------|
| 2026-04-30 | 초기 구조 (서비스 분해 전, `/chat`/`/chat-v2` 분리) |
| 2026-05-01 | 엔드포인트 통합, 서비스 6개 분해, RAG 일원화, sql_guard 강화 |
| 2026-05-02 | A–I 9개 개선 항목 적용. 본 요구사항 분석서 작성 |
