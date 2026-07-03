import { useEffect, useState } from 'react'
import { documentDownloadUrl, documentText, fetchDocumentObjectUrl } from '../api.ts'
import type { DocumentText } from '../types.ts'

type Kind = 'image' | 'pdf' | 'text'

const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff', 'tif']

function kindOf(filename: string): Kind {
  const ext = filename.toLowerCase().split('.').pop() ?? ''
  if (IMAGE_EXT.includes(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  return 'text'
}

interface Props {
  documentId: number
  filename: string
  onClose: () => void
}

/** Full-screen preview of a source document: the original (image/PDF) plus the
 *  text the RAG pipeline actually indexed. */
export function PreviewModal({ documentId, filename, onClose }: Props) {
  const kind = kindOf(filename)
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [extracted, setExtracted] = useState<DocumentText | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    let created: string | null = null

    const run = async () => {
      setLoading(true)
      setError(null)

      // Visual (image/PDF) and extracted-text loads are independent: a failure of
      // one must not blank out the other.
      const visual =
        kind === 'image' || kind === 'pdf'
          ? fetchDocumentObjectUrl(documentId)
              .then((url) => {
                created = url
                if (alive) setObjectUrl(url)
                else URL.revokeObjectURL(url)
              })
              .catch((e) => {
                if (alive) setError((e as Error).message)
              })
          : Promise.resolve()

      // The extracted text is what the AI "reads" — most useful for images
      // (vision transcription) and non-renderable Office/CSV files.
      const text =
        kind === 'image' || kind === 'text'
          ? documentText(documentId)
              .then((t) => alive && setExtracted(t))
              .catch(() => {
                /* text preview is best-effort (endpoint may be unavailable) */
              })
          : Promise.resolve()

      await Promise.all([visual, text])
      if (alive) setLoading(false)
    }
    run()

    return () => {
      alive = false
      if (created) URL.revokeObjectURL(created)
    }
  }, [documentId, kind])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__panel" onClick={(e) => e.stopPropagation()}>
        <header className="modal__head">
          <span className="modal__title" title={filename}>
            {filename}
          </span>
          <div className="modal__actions">
            <a
              className="file__dl"
              href={documentDownloadUrl(documentId)}
              download={filename}
            >
              ⬇ Download
            </a>
            <button className="modal__close" onClick={onClose} aria-label="Close preview">
              ✕
            </button>
          </div>
        </header>

        <div className="modal__body">
          {loading && <div className="modal__status">Loading preview…</div>}
          {error && (
            <div className="modal__status modal__status--error">
              Couldn't load preview: {error}
            </div>
          )}

          {!error && kind === 'image' && objectUrl && (
            <img className="preview-img" src={objectUrl} alt={filename} />
          )}
          {!error && kind === 'pdf' && objectUrl && (
            <iframe className="preview-pdf" src={objectUrl} title={filename} />
          )}

          {!error && extracted && (
            <ExtractedText data={extracted} collapsible={kind === 'image'} />
          )}

          {!loading && !error && !objectUrl && !extracted && (
            <div className="modal__status">
              No inline preview available for this file — use Download to open it.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ExtractedText({ data, collapsible }: { data: DocumentText; collapsible: boolean }) {
  const [open, setOpen] = useState(!collapsible)
  const empty = data.text.trim().length === 0

  return (
    <section className="extracted">
      <button
        type="button"
        className="extracted__toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? '▾' : '▸'} Text read by the AI
        {data.pages.length > 0 && ` · ${data.pages.length} page${data.pages.length === 1 ? '' : 's'}`}
      </button>
      {open &&
        (empty ? (
          <p className="extracted__empty">No text was extracted for this document.</p>
        ) : (
          <div className="extracted__pages">
            {data.pages.map((p) => (
              <div key={p.page_number} className="extracted__page">
                <div className="extracted__pagelabel">page {p.page_number}</div>
                <pre className="extracted__text">{p.content}</pre>
              </div>
            ))}
          </div>
        ))}
    </section>
  )
}
