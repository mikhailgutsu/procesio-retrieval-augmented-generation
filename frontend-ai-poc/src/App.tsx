import { useEffect, useRef, useState } from 'react'
import './App.css'
import { apiBase, ask, ingest } from './api.ts'
import type { ChatMessage } from './types.ts'
import { HealthBadge } from './components/HealthBadge.tsx'
import { Composer } from './components/Composer.tsx'
import { Message } from './components/Message.tsx'

const EXAMPLES = [
  'What does this document cover?',
  'Summarize the main requirements.',
  'Which page mentions the configuration steps?',
]

function newId(): string {
  return crypto.randomUUID()
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const send = async (text: string) => {
    const pendingId = newId()
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', text },
      { id: pendingId, role: 'assistant', text: '', pending: true },
    ])
    setBusy(true)
    try {
      const res = await ask(text)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
                ...m,
                pending: false,
                text: res.answer,
                answerable: res.answerable,
                citations: res.citations,
                retrieved: res.retrieved,
                highlights: res.highlights,
              }
            : m,
        ),
      )
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? { ...m, pending: false, error: true, text: `Request failed: ${(err as Error).message}` }
            : m,
        ),
      )
    } finally {
      setBusy(false)
    }
  }

  const upload = async (file: File) => {
    setUploading(true)
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', text: `📎 Uploading ${file.name}…` },
    ])
    try {
      const res = await ingest(file)
      const summary =
        res.status === 'skipped'
          ? `Already ingested "${res.filename ?? file.name}" (skipped duplicate).`
          : `Ingested "${res.filename ?? file.name}" — ${res.pages ?? '?'} pages, ${res.chunks ?? '?'} chunks. Ask me about it!`
      setMessages((prev) => [...prev, { id: newId(), role: 'assistant', text: summary, answerable: true }])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: 'assistant', error: true, text: `Upload failed: ${(err as Error).message}` },
      ])
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__logo">◆</span>
          <div>
            <h1 className="brand__title">RAG Assistant</h1>
            <p className="brand__subtitle">Chat over your ingested documents</p>
          </div>
        </div>
        <div className="topbar__right">
          <HealthBadge />
          <button
            type="button"
            className="btn btn--ghost"
            disabled={uploading}
            onClick={() => fileInput.current?.click()}
          >
            {uploading ? 'Uploading…' : '＋ Upload doc'}
          </button>
          <input
            ref={fileInput}
            type="file"
            hidden
            accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp,.webp,.pptx,.xlsx,.xlsm,.xls,.docx,.doc,.csv"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) upload(f)
            }}
          />
        </div>
      </header>

      <main className="chat" ref={scroller}>
        {messages.length === 0 ? (
          <div className="welcome">
            <h2>Ask the documentation</h2>
            <p>
              Questions run the full RAG flow on the backend: your text is embedded, matched against
              the vector index, and answered by the LLM with page-level citations.
            </p>
            <div className="welcome__examples">
              {EXAMPLES.map((q) => (
                <button key={q} type="button" className="example" onClick={() => send(q)}>
                  {q}
                </button>
              ))}
            </div>
            <p className="welcome__hint">
              No documents yet? Use <strong>＋ Upload doc</strong> above to ingest a PDF first.
            </p>
          </div>
        ) : (
          <div className="thread">
            {messages.map((m) => (
              <Message key={m.id} msg={m} />
            ))}
          </div>
        )}
      </main>

      <footer className="footer">
        <Composer disabled={busy} onSend={send} />
        <p className="footer__api">connected to {apiBase()}</p>
      </footer>
    </div>
  )
}
