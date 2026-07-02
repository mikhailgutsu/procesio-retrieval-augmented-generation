import { useState } from 'react'
import type { ChatMessage } from '../types.ts'

/** Renders one transcript entry: a user bubble, or an assistant answer + sources. */
export function Message({ msg }: { msg: ChatMessage }) {
  if (msg.role === 'user') {
    return (
      <div className="msg msg--user">
        <div className="msg__bubble">{msg.text}</div>
      </div>
    )
  }

  return (
    <div className="msg msg--assistant">
      <div className="msg__avatar" aria-hidden>
        AI
      </div>
      <div className="msg__body">
        {msg.pending ? (
          <div className="msg__bubble msg__bubble--pending">
            <span className="dots">
              <i />
              <i />
              <i />
            </span>
            Searching documents &amp; asking the model…
          </div>
        ) : (
          <div className={`msg__bubble${msg.error ? ' msg__bubble--error' : ''}`}>
            {!msg.error && msg.answerable != null && (
              <span className={`tag ${msg.answerable ? 'tag--ok' : 'tag--warn'}`}>
                {msg.answerable ? 'grounded answer' : 'not found in documents'}
              </span>
            )}
            <p className="msg__text">{msg.text}</p>
            <Sources msg={msg} />
          </div>
        )}
      </div>
    </div>
  )
}

function Sources({ msg }: { msg: ChatMessage }) {
  const [open, setOpen] = useState(false)
  const citations = msg.citations ?? []
  const retrieved = msg.retrieved ?? []
  if (citations.length === 0 && retrieved.length === 0) return null

  return (
    <div className="sources">
      <button type="button" className="sources__toggle" onClick={() => setOpen((o) => !o)}>
        {open ? '▾' : '▸'} {citations.length} source{citations.length === 1 ? '' : 's'}
        {retrieved.length > 0 && ` · ${retrieved.length} retrieved chunk${retrieved.length === 1 ? '' : 's'}`}
      </button>

      {open && (
        <div className="sources__body">
          {citations.length > 0 && (
            <ul className="chips">
              {citations.map((c, i) => (
                <li key={`c-${i}`} className="chip">
                  <span className="chip__file">{c.filename}</span>
                  <span className="chip__meta">
                    p.{c.page_number} · {c.score.toFixed(3)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {retrieved.map((r, i) => (
            <div key={`r-${i}`} className="snippet">
              <div className="snippet__head">
                <strong>{r.filename}</strong>
                <span>
                  page {r.page_number} · score {r.score.toFixed(3)}
                </span>
              </div>
              <p className="snippet__preview">{r.preview}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
