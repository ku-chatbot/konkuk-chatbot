# 시퀀스 다이어그램

> 작성일: 2026-05-02
> 대상: KU-Bot 핵심 흐름 7종 (로그인, DB 성공, LLM→룰 폴백, RAG 1차, DB 실패 후 RAG 폴백, DB 빈 결과, 인제스트)
>
> 모든 화살표에 메서드 시그니처와 실제 반환값 형태를 함께 표기합니다.

---

## 1. 로그인

```mermaid
sequenceDiagram
    autonumber
    actor User as 학생
    participant FE as LoginPage
    participant API as POST /auth/login
    participant DB as SQLite (Student)
    participant Sec as security.py

    User->>FE: 학번/비밀번호 입력<br/>(student_id: int, password: str)
    FE->>API: HTTP POST<br/>body={"student_id": 202214001, "password": "password123"}
    API->>DB: db.get(Student, payload.student_id)
    DB-->>API: Student(student_id=202214001, name="김도윤",<br/>major="컴퓨터공학부", admission_year=2022,<br/>status="재학", hashed_password="pbkdf2_sha256$...")<br/>또는 None

    alt 학생 없음
        API-->>FE: HTTPException(status_code=401,<br/>detail="학번 또는 비밀번호가 올바르지 않습니다.")
    else 학생 있음
        API->>Sec: verify_password(<br/>password="password123",<br/>password_hash=student.hashed_password)
        Sec-->>API: bool (True / False)

        alt 비밀번호 불일치
            API-->>FE: 401 Unauthorized
        else 일치
            API->>Sec: create_access_token(<br/>subject=str(student.student_id),<br/>extra={"name": student.name})
            Sec-->>API: token: str<br/>("eyJhbGc...")
            API-->>FE: TokenResponse(<br/>access_token="eyJhbGc...",<br/>token_type="bearer",<br/>student=StudentMe(...))
            FE->>FE: localStorage.setItem(<br/>'kubot_token', access_token)
        end
    end
```

---

## 2. `/chat` — DB 분기 (LLM 성공 경로)

```mermaid
sequenceDiagram
    autonumber
    actor User as 학생
    participant FE as ChatPage
    participant API as POST /chat
    participant Deps as get_current_student
    participant CS as ChatService
    participant Gen as GeneralAnswerService
    participant QR as QueryRouter
    participant T2S as TextToSQLService
    participant Guard as sql_guard
    participant Exec as SqlExecutor
    participant Sum as ResultSummarizer
    participant DB as SQLite
    participant OAI as OpenAI

    User->>FE: "내 성적 보여줘"
    FE->>API: HTTP POST<br/>headers={Authorization: "Bearer eyJ..."}<br/>body={"message": "내 성적 보여줘"}
    API->>Deps: get_current_student(<br/>credentials=HTTPAuthorizationCredentials(...),<br/>db=Session)
    Deps-->>API: Student(student_id=202214001, ...)
    API->>CS: answer(<br/>db=Session,<br/>student=Student(...),<br/>message="내 성적 보여줘")

    CS->>Gen: try_answer(message="내 성적 보여줘")
    Gen-->>CS: None  (날짜·시간 키워드 없음)

    CS->>QR: classify(db, message="내 성적 보여줘")
    QR->>DB: db.query(Course.name).all()
    DB-->>QR: [("데이터베이스",), ("자료구조",), ...]
    QR-->>CS: "db"  (DB 키워드 "내", "성적" 매칭)

    CS->>T2S: generate_with_llm(message="내 성적 보여줘")
    T2S->>OAI: complete_json(<br/>instructions=SCHEMA_DESCRIPTION + 규칙,<br/>user_input="내 성적 보여줘")
    OAI-->>T2S: {"answerable": true,<br/>"sql": "SELECT e.semester, c.name AS course_name,<br/>e.grade, c.credit FROM enrollment e<br/>JOIN course c ON ... WHERE e.student_id = :student_id",<br/>"reason": "..."}
    T2S-->>CS: GeneratedSql(sql="SELECT ...", params={})

    CS->>Guard: validate_select_sql(sql="SELECT ...")
    Guard-->>CS: (ok=True, reason=None)

    CS->>Exec: execute(<br/>db, student,<br/>sql="SELECT ...",<br/>params={})
    Exec->>Guard: validate_select_sql(sql)
    Guard-->>Exec: (True, None)
    Exec->>DB: text(sql).bindparams(<br/>{"student_id": 202214001})<br/>→ db.execute(...).fetchall()
    DB-->>Exec: [Row(semester="2026-1", course_name="데이터베이스",<br/>grade="A+", credit=3), ...]
    Exec-->>CS: [{"semester": "2026-1", "course_name": "데이터베이스",<br/>"grade": "A+", "credit": 3}, ...]  (3건)

    CS->>Sum: summarize(message="내 성적 보여줘", rows=[...3건])
    Note over Sum: len(rows) >= 2 → table 분기,<br/>LLM 호출 없이 헤드라인만 생성
    Sum-->>CS: Summary(answer="조회 결과 3건입니다.",<br/>display_format="table")

    CS->>DB: db.add(QueryLog(<br/>student_id=202214001,<br/>message="내 성적 보여줘",<br/>route="db", success=True,<br/>error=None,<br/>generated_sql="SELECT ..."))<br/>db.commit()
    DB-->>CS: ok

    CS-->>API: ChatResult(<br/>route="db",<br/>answer="조회 결과 3건입니다.",<br/>display_format="table",<br/>sql="SELECT ...",<br/>rows=[...3건],<br/>sources=[])
    API-->>FE: ChatResponse(<br/>route="db",<br/>answer="조회 결과 3건입니다.",<br/>display_format="table",<br/>sql="SELECT ...",<br/>rows=[...],<br/>sources=[])
    FE->>FE: setMessages([..., {role: "assistant",<br/>text, displayFormat, rows, sql}])
    FE-->>User: <RowTable rows={[...]} /><br/>(영→한 컬럼 매핑, 셀 포맷)
```

---

## 3. `/chat` — DB 분기에서 LLM 실패 → 룰 fallback (B 변경)

```mermaid
sequenceDiagram
    autonumber
    participant CS as ChatService
    participant T2S as TextToSQLService
    participant Guard as sql_guard
    participant Exec as SqlExecutor
    participant DB as SQLite
    participant OAI as OpenAI

    Note over CS: route == "db"

    CS->>T2S: generate_with_llm(message="이번 학기 등록금 얼마야?")
    T2S->>OAI: complete_json(instructions, user_input)
    OAI-->>T2S: {"answerable": true,<br/>"sql": "SELECT amount FROM tuition<br/>WHERE student_id = 202214002"}<br/>(잘못된 학번 리터럴)
    T2S-->>CS: GeneratedSql(sql="SELECT ... = 202214002", params={})

    CS->>T2S: generate_with_rules(message="이번 학기 등록금 얼마야?")
    T2S-->>CS: GeneratedSql(<br/>sql="SELECT semester, amount, payment_status<br/>FROM tuition WHERE student_id = :student_id<br/>ORDER BY semester DESC LIMIT 3",<br/>params={})

    Note over CS: candidates = [("llm", llm_sql), ("rule", rule_sql)]

    CS->>Guard: validate_select_sql(LLM_sql)
    Guard-->>CS: (False,<br/>"학번 리터럴은 허용되지 않습니다.<br/>:student_id 바인딩만 사용하세요.")
    Note over CS: errors.append("llm_sql_rejected_by_guard")

    CS->>Guard: validate_select_sql(Rule_sql)
    Guard-->>CS: (True, None)

    CS->>Exec: execute(db, student,<br/>sql=Rule_sql,<br/>params={})
    Exec->>DB: text(sql).bindparams(<br/>{"student_id": 202214001})
    DB-->>Exec: [Row(semester="2026-1",<br/>amount=4_100_000,<br/>payment_status=True)]
    Exec-->>CS: [{"semester": "2026-1",<br/>"amount": 4_100_000,<br/>"payment_status": True}]  (1건)

    Note over CS: rows 있음 → 룰 후보로 답변 성공.<br/>1건이므로 summary 분기 (LLM 산문 시도).

    CS->>DB: db.add(QueryLog(<br/>route="db",<br/>success=True,<br/>error="llm_sql_rejected_by_guard",<br/>generated_sql=Rule_sql))
    DB-->>CS: ok
    CS-->>CS: ChatResult(route="db",<br/>display_format="summary",<br/>sql=Rule_sql, rows=[1건])
```

---

## 4. `/chat` — RAG 분기 (1차 선택)

```mermaid
sequenceDiagram
    autonumber
    actor User as 학생
    participant FE as ChatPage
    participant CS as ChatService
    participant QR as QueryRouter
    participant RAG as ReferenceRAGService
    participant LE as LocalEmbeddingService
    participant FAISS as FaissVectorStore
    participant DB as SQLite
    participant OAI as OpenAI

    User->>FE: "휴학 신청은 어떻게 해?"
    FE->>CS: answer(db, student, message="휴학 신청은 어떻게 해?")

    CS->>QR: classify(db, message)
    QR-->>CS: "reference_rag"<br/>("휴학" ∈ REFERENCE_KEYWORDS)

    Note over CS: DB 분기 건너뜀 (attempt = None)

    CS->>RAG: answer(db, message="휴학 신청은 어떻게 해?",<br/>top_k=5)

    RAG->>LE: embed(text="휴학 신청은 어떻게 해?")
    LE-->>RAG: query_vector: ndarray(float32, shape=(768,))<br/>(KURE-v1, normalize_embeddings=True)

    RAG->>FAISS: search(query_vector, top_k=5)
    FAISS-->>RAG: [VectorSearchResult(vector_id=12, score=0.83),<br/>VectorSearchResult(vector_id=27, score=0.79),<br/>... 총 5개]

    RAG->>DB: db.query(ReferenceChunk).join(ReferenceDocument)<br/>.filter(status=="ready",<br/>vector_id.in_([12,27,...]))
    DB-->>RAG: [ReferenceChunk(id=12, content="...",<br/>page_start=3, heading="휴학 신청",<br/>document=ReferenceDocument(title="신입생 가이드북",<br/>source_url="https://...")), ...]

    RAG->>RAG: _format_context(chunks)<br/>→ "[1] title: ... / page: 3 / heading: 휴학 신청\nurl: ...\ncontent: ...\n\n[2] ..."

    RAG->>OAI: complete_text(<br/>instructions="문서 발췌문 안에서만 답하세요...",<br/>user_input="질문: ...\n\n참고문서:\n[1] ...")
    OAI-->>RAG: "휴학 신청은 학기 개시 전 지정 기간에 포털에서...<br/>\n\n참고\n- 신입생 가이드북, p.3 - https://..."

    RAG-->>CS: ReferenceRAGAnswer(<br/>route="reference_rag",<br/>answer="휴학 신청은 ...",<br/>sources=["신입생 가이드북, p.3 - https://..."])

    CS->>DB: db.add(QueryLog(<br/>route="reference_rag",<br/>success=True,<br/>error=None,<br/>generated_sql=None))
    DB-->>CS: ok

    CS-->>FE: ChatResponse(<br/>route="reference_rag",<br/>answer="휴학 신청은 ...",<br/>display_format="summary",<br/>sql=None,<br/>rows=[],<br/>sources=["신입생 가이드북, p.3 - https://..."])
    FE-->>User: 답변 + 출처 메타 표시
```

---

## 5. `/chat` — DB 실패 후 RAG 폴백 (route 메타: `reference_rag_after_db_failed`)

```mermaid
sequenceDiagram
    autonumber
    participant CS as ChatService
    participant QR as QueryRouter
    participant T2S as TextToSQLService
    participant RAG as ReferenceRAGService
    participant DB as SQLite

    Note over CS: route == "db"

    CS->>T2S: generate_with_llm(message)
    T2S-->>CS: None<br/>(OpenAI 키 없음 또는 unanswerable)

    CS->>T2S: generate_with_rules(message)
    T2S-->>CS: None<br/>(어느 키워드 룰에도 안 걸림)

    Note over CS: candidates = []<br/>attempt = DbAttempt(<br/>result=None, sql=None,<br/>errors=["no_sql_candidates_generated"])

    CS->>RAG: answer(db, message, top_k=5)
    RAG-->>CS: ReferenceRAGAnswer(<br/>route="reference_rag",<br/>answer="...",<br/>sources=["..."])

    CS->>DB: db.add(QueryLog(<br/>route="reference_rag_after_db_failed",<br/>success=True,  (sources 비어있지 않음)<br/>error="no_sql_candidates_generated",<br/>generated_sql=None))
    DB-->>CS: ok

    CS-->>CS: ChatResult(<br/>route="reference_rag",<br/>answer="...",<br/>sources=[...])

    Note over CS: 사용자 응답의 route는 "reference_rag",<br/>메타 라우트 _after_db_failed는 로그에만 기록
```

---

## 6. `/chat` — DB 빈 결과 (route 메타: `db_no_result`)

```mermaid
sequenceDiagram
    autonumber
    participant CS as ChatService
    participant T2S as TextToSQLService
    participant Guard as sql_guard
    participant Exec as SqlExecutor
    participant DB as SQLite

    Note over CS: route == "db"

    CS->>T2S: generate_with_llm(message)
    T2S-->>CS: None

    CS->>T2S: generate_with_rules(message="이번 학기 등록금 얼마야?")
    T2S-->>CS: GeneratedSql(<br/>sql="SELECT semester, amount, payment_status<br/>FROM tuition WHERE student_id = :student_id<br/>AND semester = '1900-1'",<br/>params={})

    CS->>Guard: validate_select_sql(sql)
    Guard-->>CS: (True, None)

    CS->>Exec: execute(db, student, sql, params={})
    Exec->>DB: text(sql).bindparams(<br/>{"student_id": 202214001})
    DB-->>Exec: []  (0건)
    Exec-->>CS: []

    Note over CS: last_executed = candidate<br/>errors.append("rule_sql_no_rows")<br/>has_answer == False, is_empty_result == True

    CS->>DB: db.add(QueryLog(<br/>route="db_no_result",<br/>success=False,<br/>error="rule_sql_no_rows",<br/>generated_sql=sql))
    DB-->>CS: ok

    CS-->>CS: ChatResult(<br/>route="db",<br/>answer="조회 결과가 없습니다.<br/>질문의 과목명이나 학기를 조금 더 구체적으로 적어주세요.",<br/>display_format="summary",<br/>sql=last_executed.sql,<br/>rows=[])
```

---

## 7. 문서 인제스트 (오프라인 배치)

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 관리자
    participant Script as ingest_documents.py
    participant Manifest as document_manifest
    participant Ing as document_ingestion
    participant UP as Upstage Parser
    participant DP as document_parser
    participant DB as SQLite
    participant LE as LocalEmbeddingService
    participant FAISS as FaissVectorStore
    participant FS as parsed_documents/

    Admin->>Script: python -m app.scripts.ingest_documents
    Script->>DB: create_tables()<br/>(Base.metadata.create_all(bind=engine))
    Script->>Ing: ingest_reference_documents(<br/>db=Session,<br/>manifest_path=Path("data/raw_documents/source_urls.txt"),<br/>raw_dir=Path("data/raw_documents"))

    Ing->>Manifest: load_document_sources(<br/>path=manifest_path)
    Manifest-->>Ing: [DocumentSource(<br/>file="01_university/...pdf",<br/>title="2026 신입생 가이드북",<br/>category="university",<br/>url="https://..."), ...]  (5개)

    loop 각 PDF (DocumentSource)
        Ing->>DB: db.query(ReferenceDocument)<br/>.filter(file_path == source.file).first()
        DB-->>Ing: ReferenceDocument or None

        alt status == "ready" and chunks 있음
            Note over Ing: 스킵, stats unchanged
        else 신규/재처리
            Ing->>UP: parse(pdf_path=Path("data/raw_documents/.../...pdf"))
            UP-->>Ing: parse_result: dict<br/>{"content": {"markdown": "...", "html": "..."},<br/>"elements": [{...}, ...],<br/>"usage": {"pages": N}}

            Ing->>FS: write_text(<br/>raw_response_path,  json.dumps(parse_result),<br/>markdown_path,      extract_markdown(parse_result),<br/>html_path,          extract_html(parse_result))
            FS-->>Ing: ok

            Ing->>DP: extract_chunks(<br/>parse_result,<br/>max_chars=1800)
            DP-->>Ing: [ParsedChunk(content="...",<br/>page_start=1, page_end=1,<br/>heading="휴학 신청"), ...]  (M개)

            loop 각 ParsedChunk
                Ing->>DB: db.add(ReferenceChunk(<br/>document_id=document.id,<br/>chunk_index=i,<br/>content=parsed.content,<br/>page_start, page_end, heading,<br/>token_count=len(content.split())))
            end

            Ing->>DB: chunks = ... .order_by(chunk_index).all()<br/>for chunk in chunks: chunk.vector_id = chunk.id<br/>document.status = "ready"<br/>db.commit()
        end
    end

    Ing->>DB: db.query(<br/>ReferenceChunk.vector_id,<br/>ReferenceChunk.content)<br/>.join(ReferenceDocument)<br/>.filter(status=="ready",<br/>vector_id IS NOT NULL)
    DB-->>Ing: [(vector_id, content), ...]  (총 ΣM 행)

    Ing->>LE: embed_many(<br/>texts=[content[:2500] for ...])
    Note over LE: KURE-v1, CPU,<br/>normalize_embeddings=True
    LE-->>Ing: vectors: ndarray(float32, shape=(ΣM, 768))

    Ing->>FAISS: save(<br/>vectors=vectors,<br/>vector_ids=[v_id for ...])
    FAISS->>FS: write_index(<br/>data/vector_index/reference_chunks.faiss,<br/>reference_chunks.npy,<br/>reference_chunks.ids.npy)
    FS-->>FAISS: ok

    Ing-->>Script: stats = {"documents": N,<br/>"chunks": ΣM,<br/>"failed": F}
    Script-->>Admin: print("ingestion complete:<br/>documents=N chunks=ΣM failed=F")
```
