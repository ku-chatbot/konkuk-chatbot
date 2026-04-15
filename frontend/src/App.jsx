import React, { useEffect, useState } from 'react'
import { api, clearToken, getToken, setToken } from './api/client'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'

export default function App() {
  const [student, setStudent] = useState(null)
  const [loading, setLoading] = useState(Boolean(getToken()))

  useEffect(() => {
    if (!getToken()) return
    api('/students/me')
      .then(setStudent)
      .catch(() => clearToken())
      .finally(() => setLoading(false))
  }, [])

  async function handleLogin(studentId, password) {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ student_id: Number(studentId), password }),
    })
    setToken(data.access_token)
    setStudent(data.student)
  }

  function handleLogout() {
    clearToken()
    setStudent(null)
  }

  if (loading) {
    return <main className="loading-screen">KU-Bot 연결 중</main>
  }

  return student ? (
    <ChatPage student={student} onLogout={handleLogout} />
  ) : (
    <LoginPage onLogin={handleLogin} />
  )
}
