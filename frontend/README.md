# KU-Bot Frontend

React + Vite 기반 챗봇 UI입니다. 로그인 후 KU-Bot 채팅 화면에서 내부 DB, 공식 문서 RAG, 웹검색 답변을 확인할 수 있습니다.

답변 대기 중에는 `/chat/progress/{request_id}`를 폴링해 현재 처리 단계와 planner 검색 키워드를 표시합니다.

## 실행

```bash
cd frontend
npm install
npm run dev
```

백엔드 주소를 바꾸려면 `.env`에 다음 값을 넣으세요.

```bash
VITE_API_BASE=http://localhost:8000
```

## 빌드 확인

```bash
npm run build
```

## 주요 화면 동작

- 로그인 성공 시 `/students/me`로 사용자 정보를 가져옵니다.
- 채팅 전송 시 `POST /chat`에 `message`와 `request_id`를 보냅니다.
- 답변 대기 중 `GET /chat/progress/{request_id}`를 주기적으로 호출합니다.
- 서버가 `route`, `sql` 같은 내부 값을 내려줘도 UI에는 내부 라우팅 문자열이나 실행 SQL을 노출하지 않습니다.
