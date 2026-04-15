import React, { useState } from 'react'

const campusImage =
  'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?auto=format&fit=crop&w=1600&q=80'

export default function LoginPage({ onLogin }) {
  const [studentId, setStudentId] = useState('202214001')
  const [password, setPassword] = useState('password123')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      await onLogin(studentId, password)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="login-page">
      <img className="login-bg" src={campusImage} alt="푸른 캠퍼스 전경" />
      <section className="login-shell" aria-label="KU-Bot 로그인">
        <div className="brand-block">
          <div className="ku-mark">KU</div>
          <p>KONKUK UNIVERSITY</p>
          <h1>KU-Bot</h1>
          <span>학사정보를 가장 빠르게 묻는 곳</span>
        </div>

        <form className="login-panel" onSubmit={submit}>
          <h2>로그인</h2>
          <label>
            학번
            <input
              type="number"
              value={studentId}
              onChange={(event) => setStudentId(event.target.value)}
              placeholder="202214001"
              required
            />
          </label>
          <label>
            비밀번호
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="password123"
              required
            />
          </label>
          {error && <p className="form-error">{error}</p>}
          <button type="submit" disabled={loading}>
            {loading ? '확인 중' : 'KU-Bot 시작'}
          </button>
          <p className="demo-note">테스트 계정: 202214001 / password123</p>
        </form>
      </section>
    </main>
  )
}
