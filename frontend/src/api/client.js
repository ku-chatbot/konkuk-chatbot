const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export function getToken() {
  return localStorage.getItem('kubot_token')
}

export function setToken(token) {
  localStorage.setItem('kubot_token', token)
}

export function clearToken() {
  localStorage.removeItem('kubot_token')
}

export async function api(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  }
  const token = getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || '요청을 처리하지 못했습니다.')
  }
  return data
}
