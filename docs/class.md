# 클래스 다이어그램

> 작성일: 2026-05-02
> 대상: KU-Bot 백엔드 (`backend/app/`)

---

## 1. 서비스 계층 (분해된 6개 서비스 + DTO)

```mermaid
classDiagram
    direction LR

    class ChatService {
        +router: QueryRouter
        +general: GeneralAnswerService
        +text_to_sql: TextToSQLService
        +executor: SqlExecutor
        +summarizer: ResultSummarizer
        +answer(db, student, message) ChatResult
        -_answer_from_db(db, student, message) DbAttempt
        -_log(db, student_id, message, route, sql, success, error)
    }

    class GeneralAnswerService {
        +DATE_WORDS: tuple
        +TIME_WORDS: tuple
        +try_answer(message) GeneralAnswer?
    }

    class QueryRouter {
        +DB_KEYWORDS: tuple
        +REFERENCE_KEYWORDS: tuple
        +classify(db, message) Route
    }

    class TextToSQLService {
        +generate_with_llm(message) GeneratedSql?
        +generate_with_rules(message) GeneratedSql?
        -_sql_with_openai(message) str?
        -_fallback_sql(message) GeneratedSql?
        -_course_filter(message) str?
    }

    class SqlExecutor {
        +execute(db, student, sql, params) list~dict~
    }

    class ResultSummarizer {
        +INSTRUCTIONS: str
        +summarize(message, rows) Summary
        -_headline(rows) str
        -_llm_summary(message, rows) str
    }

    class ReferenceRAGService {
        +answer(db, message, top_k) ReferenceRAGAnswer
        -_retrieve(db, message, top_k) list~ReferenceChunk~
        -_format_context(chunks) str
        -_sources(chunks) list~ReferenceSource~
        -_fallback_answer(chunks) str
    }

    class ChatResult {
        +route: str
        +answer: str
        +display_format: str
        +sql: str?
        +rows: list~dict~
        +sources: list~str~
    }

    class DbAttempt {
        +result: ChatResult?
        +sql: str?
        +errors: list~str~
        +has_answer: bool
        +is_empty_result: bool
    }

    class GeneratedSql {
        +sql: str
        +params: dict
    }

    class Summary {
        +answer: str
        +display_format: str
    }

    class GeneralAnswer {
        +answer: str
    }

    class ReferenceRAGAnswer {
        +route: str
        +answer: str
        +sources: list~str~
    }

    ChatService --> QueryRouter
    ChatService --> GeneralAnswerService
    ChatService --> TextToSQLService
    ChatService --> SqlExecutor
    ChatService --> ResultSummarizer
    ChatService --> ReferenceRAGService
    ChatService ..> ChatResult : returns
    ChatService ..> DbAttempt : uses
    GeneralAnswerService ..> GeneralAnswer : returns
    TextToSQLService ..> GeneratedSql : returns
    ResultSummarizer ..> Summary : returns
    ReferenceRAGService ..> ReferenceRAGAnswer : returns
```

---

## 2. 보조 모듈 (보안 가드 · 외부 API · RAG 인프라)

```mermaid
classDiagram
    direction LR

    class sql_guard {
        <<module>>
        +ALLOWED_TABLES: set
        +BLOCKED_KEYWORDS: set
        +STUDENT_SCOPED_TABLES: set
        +validate_select_sql(sql) tuple~bool, str?~
    }

    class OpenAIService {
        +client: OpenAI?
        +complete_json(instructions, user_input) dict?
        +complete_text(instructions, user_input) str?
        +embed(text) list~float~?
    }

    class LocalEmbeddingService {
        +model: SentenceTransformer
        +embed(text) ndarray
        +embed_many(texts) ndarray
    }

    class FaissVectorStore {
        +index_path: Path
        +save(vectors, vector_ids)
        +search(query_vector, top_k) list~VectorSearchResult~
    }

    class VectorSearchResult {
        +vector_id: int
        +score: float
    }

    class UpstageDocumentParser {
        +parse(pdf_path) dict
        +parse_sync(pdf_path) dict
        +parse_async(pdf_path) dict
    }

    class document_parser {
        <<module>>
        +extract_chunks(parse_result, max_chars) list~ParsedChunk~
        +extract_markdown(parse_result) str
        +extract_html(parse_result) str
    }

    class ParsedChunk {
        +content: str
        +page_start: int?
        +page_end: int?
        +heading: str?
    }

    class document_ingestion {
        <<module>>
        +ingest_reference_documents(db, manifest_path, raw_dir)
    }

    class DocumentSource {
        +file: str
        +title: str
        +category: str
        +url: str
    }

    SqlExecutor ..> sql_guard : uses
    TextToSQLService ..> OpenAIService : uses
    ResultSummarizer ..> OpenAIService : uses
    ReferenceRAGService ..> OpenAIService : uses
    ReferenceRAGService ..> LocalEmbeddingService : uses
    ReferenceRAGService ..> FaissVectorStore : uses
    FaissVectorStore ..> VectorSearchResult : returns
    document_ingestion ..> UpstageDocumentParser : uses
    document_ingestion ..> document_parser : uses
    document_ingestion ..> LocalEmbeddingService : uses
    document_ingestion ..> FaissVectorStore : uses
    document_ingestion ..> DocumentSource : uses
    document_parser ..> ParsedChunk : returns
```

---

## 3. ORM 모델 (`app/models/academic.py`)

```mermaid
classDiagram
    direction LR

    class Student {
        +student_id: int PK
        +name: str
        +major: str
        +admission_year: int
        +status: str
        +hashed_password: str
        +enrollments: list~Enrollment~
        +tuitions: list~Tuition~
    }

    class Professor {
        +professor_id: int PK
        +name: str
        +email: str
        +office: str
        +courses: list~Course~
    }

    class Course {
        +course_id: int PK
        +name: str
        +credit: int
        +room: str
        +description: str
        +professor_id: int FK
        +professor: Professor
        +enrollments: list~Enrollment~
        +schedules: list~Schedule~
        +required_prerequisites: list~Prerequisite~
        +is_prerequisite_for: list~Prerequisite~
    }

    class Enrollment {
        +enrollment_id: int PK
        +semester: str
        +grade: str?
        +student_id: int FK
        +course_id: int FK
    }

    class Schedule {
        +schedule_id: int PK
        +day_of_week: str
        +start_time: str
        +end_time: str
        +room: str
        +course_id: int FK
    }

    class Tuition {
        +tuition_id: int PK
        +semester: str
        +amount: int
        +payment_status: bool
        +student_id: int FK
    }

    class Prerequisite {
        +id: int PK
        +course_id: int FK
        +pre_course_id: int FK
    }

    class QueryLog {
        +id: int PK
        +student_id: int?
        +message: str
        +route: str
        +generated_sql: str?
        +success: bool
        +error: str?
        +created_at: datetime
    }

    class ReferenceDocument {
        +id: int PK
        +file_path: str UK
        +title: str
        +category: str
        +source_url: str
        +parsed_markdown_path: str?
        +parsed_html_path: str?
        +raw_response_path: str?
        +parser: str
        +status: str
        +error: str?
        +chunks: list~ReferenceChunk~
    }

    class ReferenceChunk {
        +id: int PK
        +document_id: int FK
        +chunk_index: int
        +content: str
        +page_start: int?
        +page_end: int?
        +heading: str?
        +vector_id: int? UK
        +token_count: int
    }

    Student "1" --> "*" Enrollment
    Student "1" --> "*" Tuition
    Professor "1" --> "*" Course
    Course "1" --> "*" Enrollment
    Course "1" --> "*" Schedule
    Course "1" --> "*" Prerequisite : as required
    Course "1" --> "*" Prerequisite : as prereq
    ReferenceDocument "1" --> "*" ReferenceChunk
```

---

## 4. 라우터·의존성 계층

```mermaid
classDiagram
    direction LR

    class FastAPI_App {
        <<main.py>>
        +include_router(auth)
        +include_router(students)
        +include_router(chat)
        +include_router(mcp)
    }

    class auth_router {
        <<routers/auth.py>>
        +POST /auth/login
        +POST /auth/logout
        +GET /auth/me
    }

    class students_router {
        <<routers/students.py>>
        +GET /students/me
    }

    class chat_router {
        <<routers/chat.py>>
        +POST /chat
    }

    class mcp_router {
        <<routers/mcp.py>>
        +GET /mcp/schema
        +POST /mcp/query
    }

    class deps {
        <<routers/deps.py>>
        +get_current_student(credentials, db) Student
    }

    class security {
        <<core/security.py>>
        +hash_password(password, salt) str
        +verify_password(password, hash) bool
        +create_access_token(subject, extra) str
        +decode_access_token(token) dict?
    }

    class get_db {
        <<db/session.py>>
    }

    FastAPI_App --> auth_router
    FastAPI_App --> students_router
    FastAPI_App --> chat_router
    FastAPI_App --> mcp_router
    auth_router ..> security
    auth_router ..> get_db
    students_router ..> deps
    chat_router ..> deps
    chat_router ..> ChatService
    mcp_router ..> deps
    mcp_router ..> SqlExecutor
    deps ..> security
    deps ..> get_db
```
