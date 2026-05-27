# KU-Bot Backend

FastAPI 기반 학사정보 챗봇 백엔드입니다. 내부 SQLite DB, 공식 학사문서 RAG, Tavily 웹검색, 복합 질문 planner를 사용해 질문 유형별로 답변합니다.

## 실행

### 1. 환경 설정

```bash
cd backend
conda activate kubot-py312
pip install -r requirements.txt
cp .env.example .env
```

OpenAI API를 사용하려면 `.env`의 `OPENAI_API_KEY`를 채우세요. 웹검색을 쓰려면 `ENABLE_WEB_SEARCH=true`와 `TAVILY_API_KEY`가 필요합니다.

### 2. 임베딩 서버

공식 문서 RAG는 `BAAI/bge-m3` 기반 로컬 임베딩 서버를 기본으로 사용합니다.

```bash
TOKENIZERS_PARALLELISM=false \
OMP_NUM_THREADS=1 \
MKL_NUM_THREADS=1 \
uvicorn app.embedding_server:app --host 127.0.0.1 --port 9000 --loop asyncio --http h11
```

### 3. 메인 서버

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop asyncio --http h11
```

개발 중 자동 재시작이 필요하면 `--reload`를 붙일 수 있습니다.

## 답변 라우팅

- `db`: 성적, 시간표, 등록금, 수강 과목, 교수 이메일/연구실, 강의실, 선수과목
- `reference_rag`: 휴학, 복학, 장학, 졸업요건, 수강신청/정정 등 공식 학사문서 질문
- `web_search`: 학과장, 최신 공지, 행사 일정처럼 최신 공식 홈페이지 확인이 필요한 질문
- `planned`: 계절학기 전공 인정, 과목 추천처럼 DB와 공식문서 근거를 함께 봐야 하는 질문

개인정보성 DB 조회는 로그인한 `student_id` 기준으로 제한하며, 다른 학생 이름/학번이 포함된 성적/수강 요청은 차단합니다.

## 문서 검색 구조

- 원문/메타데이터: SQLite `reference_document`, `reference_chunk`
- 벡터 인덱스: `data/vector_index/reference_chunks.faiss`
- 벡터 ID 매핑: `data/vector_index/reference_chunks.npy`
- 임베딩 모델: `.env`의 `LOCAL_EMBEDDING_MODEL` (`BAAI/bge-m3`)

FAISS는 벡터 검색만 담당하고, 실제 chunk 본문과 출처는 SQLite에서 조회합니다.

## 테스트 계정

- 학번: `202214001`부터 `202214100`
- 비밀번호: `password123`

## 주요 API

- `POST /auth/login`
- `GET /students/me`
- `POST /chat`
- `GET /chat/progress/{request_id}`
- `GET /mcp/schema`
- `POST /mcp/query`

## 점검 명령

```bash
python -m py_compile app/services/query_service.py app/services/reference_rag_service.py app/services/web_search_service.py
```

## Hugging Face Space 배포

무료 배포에서 `BAAI/bge-m3`를 유지하려면 Docker Space를 사용합니다. `backend` 폴더에는 Space 배포용 파일이 포함되어 있습니다.

- `Dockerfile`: Python 3.12 환경에서 백엔드 의존성을 설치하고 `start_hf.sh` 실행
- `start_hf.sh`: 임베딩 서버(`127.0.0.1:9000`)와 메인 FastAPI 서버(`0.0.0.0:7860`)를 함께 실행
- `SPACE_README.md`: Hugging Face Space의 `README.md`로 사용할 설정 파일

Space repo에는 `backend` 폴더 안의 파일들을 복사하되, `SPACE_README.md`는 Space repo의 `README.md`로 이름을 바꿔 넣습니다. `.env`는 복사하지 말고 Space의 `Settings > Variables and secrets`에 Secret으로 등록합니다.
