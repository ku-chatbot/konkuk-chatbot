import React from 'react'
import RowTable from './RowTable'

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  const showTable = !isUser && message.displayFormat === 'table' && message.rows?.length > 0
  return (
    <article className={`message ${isUser ? 'user-message' : 'assistant-message'}`}>
      <p>{message.text}</p>
      {showTable && <RowTable rows={message.rows} />}
      {!isUser && message.route && message.route !== 'system' && (
        <div className="message-meta">
          <span>{message.route === 'db' ? '내부 DB' : message.route === 'reference_rag' ? '학사정보' : message.route}</span>
          {message.sources?.length > 0 && <span>{message.sources.join(', ')}</span>}
        </div>
      )}
      {!isUser && message.sql && (
        <details>
          <summary>실행 SQL</summary>
          <code>{message.sql}</code>
        </details>
      )}
    </article>
  )
}
