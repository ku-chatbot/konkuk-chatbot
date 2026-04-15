import React, { useMemo, useState } from 'react'
import { api } from '../api/client'
import MessageBubble from '../components/MessageBubble'

const examples = [
  '내 수강 과목 알려줘',
  '내 성적 보여줘',
  '오늘 시간표 알려줘',
  '데이터베이스 교수님 이메일 알려줘',
  '이번 학기 등록금 얼마야?',
  '운영체제 선수과목 알려줘',
  '휴학 신청은 어떻게 해?',
  '졸업 요건 알려줘',
]

export default function ChatPage({ student, onLogout }) {
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: `${student.name}님, 무엇을 도와드릴까요? 내부 학사 DB를 먼저 확인하고, 필요한 경우 학사정보 문서에서 답변합니다.`,
      route: 'system',
    },
  ])
  const [loading, setLoading] = useState(false)

  const profile = useMemo(
    () => `${student.major} · ${student.student_id} · ${student.status}`,
    [student],
  )

  async function send(text = message) {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    setMessage('')
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setLoading(true)
    try {
      const data = await api('/chat', {
        method: 'POST',
        body: JSON.stringify({ message: trimmed }),
      })
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: data.answer,
          route: data.route,
          sql: data.sql,
          sources: data.sources,
        },
      ])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: err.message, route: 'error' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="chat-page">
      <aside className="side-panel">
        <div className="side-brand">
          <div className="ku-mark small">KU</div>
          <div>
            <strong>KU-Bot</strong>
            <span>Academic Assistant</span>
          </div>
        </div>
        <section className="student-strip">
          <p>{student.name}</p>
          <span>{profile}</span>
        </section>
        <section className="example-list">
          <h2>바로 묻기</h2>
          {examples.map((example) => (
            <button key={example} type="button" onClick={() => send(example)}>
              {example}
            </button>
          ))}
        </section>
        <button className="logout-button" type="button" onClick={onLogout}>
          로그아웃
        </button>
      </aside>

      <section className="chat-workspace">
        <header className="chat-header">
          <div>
            <p>건국대학교 학사정보</p>
            <h1>무엇이 궁금한가요?</h1>
          </div>
          <span>DB 우선 · 학사문서 검색</span>
        </header>

        <div className="message-list" aria-live="polite">
          {messages.map((item, index) => (
            <MessageBubble key={`${item.role}-${index}`} message={item} />
          ))}
          {loading && <MessageBubble message={{ role: 'assistant', text: '확인하고 있습니다.', route: 'loading' }} />}
        </div>

        <form
          className="chat-input"
          onSubmit={(event) => {
            event.preventDefault()
            send()
          }}
        >
          <input
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="예: 데이터베이스 수업 강의실 어디야?"
          />
          <button type="submit" disabled={loading}>
            전송
          </button>
        </form>
      </section>
    </main>
  )
}
