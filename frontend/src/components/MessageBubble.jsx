import React from 'react'

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  const isLoading = message.route === 'loading'
  return (
    <article className={`message ${isUser ? 'user-message' : 'assistant-message'} ${isLoading ? 'loading-message' : ''}`}>
      <p>{message.text}</p>
      {isLoading && (
        <div className="work-indicator" aria-label="답변 생성 중">
          <span className="work-indicator-ring" />
          <span className="work-indicator-track">
            <span />
          </span>
        </div>
      )}
      {message.detail && <small className="message-detail">{message.detail}</small>}
      {isLoading && message.keywords?.length > 0 && (
        <div className="progress-keywords">
          {message.keywords.map((keyword) => (
            <span key={keyword}>{keyword}</span>
          ))}
        </div>
      )}
      {!isUser && message.sources?.length > 0 && (
        <div className="message-meta">
          <span>출처 {message.sources.length}개</span>
          <span>{message.sources.join(', ')}</span>
        </div>
      )}
    </article>
  )
}
