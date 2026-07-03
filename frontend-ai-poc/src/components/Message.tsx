import { useState } from 'react'
import { documentDownloadUrl } from '../api.ts'
import type { ChatMessage, Citation } from '../types.ts'
import { PreviewModal } from './PreviewModal.tsx'

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

interface FileRef {
  document_id: number
  filename: string
  pages: number[]
  score: number
}

/** Collapse per-page citations into one entry per source document. */
function uniqueFiles(citations: Citation[]): FileRef[] {
  const byDoc = new Map<number, FileRef>()
  for (const c of citations) {
    const existing = byDoc.get(c.document_id)
    if (existing) {
      if (!existing.pages.includes(c.page_number)) existing.pages.push(c.page_number)
      existing.score = Math.max(existing.score, c.score)
    } else {
      byDoc.set(c.document_id, {
        document_id: c.document_id,
        filename: c.filename,
        pages: [c.page_number],
        score: c.score,
      })
    }
  }
  return [...byDoc.values()]
    .map((f) => ({ ...f, pages: f.pages.sort((a, b) => a - b) }))
    .sort((a, b) => b.score - a.score)
}

function Sources({ msg }: { msg: ChatMessage }) {
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<FileRef | null>(null)
  const citations = msg.citations ?? []
  const retrieved = msg.retrieved ?? []
  const files = uniqueFiles(citations)
  if (files.length === 0 && retrieved.length === 0) return null

  return (
    <div className="sources">
      {files.length > 0 && (
        <div className="files">
          <div className="files__label">
            Source file{files.length === 1 ? '' : 's'}
          </div>
          <ul className="files__list">
            {files.map((f) => (
              <li key={f.document_id} className="file">
                <div className="file__info">
                  <span className="file__name" title={f.filename}>
                    {f.filename}
                  </span>
                  <span className="file__meta">
                    page{f.pages.length === 1 ? '' : 's'} {f.pages.join(', ')} · {f.score.toFixed(3)}
                  </span>
                </div>
                <div className="file__actions">
                  <button
                    type="button"
                    className="file__btn"
                    onClick={() => setPreview(f)}
                    title={`Preview ${f.filename}`}
                  >
                    👁 Preview
                  </button>
                  <a
                    className="file__dl"
                    href={documentDownloadUrl(f.document_id)}
                    download={f.filename}
                    title={`Download ${f.filename}`}
                  >
                    ⬇ Download
                  </a>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {preview && (
        <PreviewModal
          documentId={preview.document_id}
          filename={preview.filename}
          onClose={() => setPreview(null)}
        />
      )}

      {retrieved.length > 0 && (
        <div className="previews">
          <button type="button" className="sources__toggle" onClick={() => setOpen((o) => !o)}>
            {open ? '▾' : '▸'} {retrieved.length} retrieved chunk{retrieved.length === 1 ? '' : 's'}
          </button>
          {open && (
            <div className="previews__body">
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
      )}
    </div>
  )
}
