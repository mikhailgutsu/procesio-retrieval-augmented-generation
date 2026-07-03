// Thin client for the RAG FastAPI backend.
//
// The base URL is read from VITE_API_BASE (see .env.example) and defaults to the
// Docker-exposed backend at http://localhost:8000. CORS is enabled server-side.

import type { AskResponse, DocumentText, HealthResponse, IngestResponse } from './types.ts'

const BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/+$/, '')

export function apiBase(): string {
  return BASE
}

/** URL to download the original source file of a document (served as attachment). */
export function documentDownloadUrl(documentId: number): string {
  return `${BASE}/documents/${documentId}/download`
}

/**
 * Fetch a document's original file and return an object URL for inline preview
 * (image / PDF). Using a blob URL means the browser renders it regardless of the
 * server's content-disposition. Caller must URL.revokeObjectURL when done.
 */
export async function fetchDocumentObjectUrl(documentId: number): Promise<string> {
  const res = await fetch(`${BASE}/documents/${documentId}/download?inline=true`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return URL.createObjectURL(await res.blob())
}

/** The text the RAG pipeline extracted/indexed for a document (OCR / vision / native). */
export async function documentText(documentId: number): Promise<DocumentText> {
  const res = await fetch(`${BASE}/documents/${documentId}/text`)
  return unwrap<DocumentText>(res)
}

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (body?.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      }
    } catch {
      // response had no JSON body — keep the status line
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

/** Ask a question — runs the full RAG flow (embed → retrieve → LLM extract). */
export async function ask(
  question: string,
  opts: { k?: number; highlight?: boolean } = {},
): Promise<AskResponse> {
  const res = await fetch(`${BASE}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      k: opts.k,
      highlight: opts.highlight ?? true,
    }),
  })
  return unwrap<AskResponse>(res)
}

/** Liveness + DB connectivity + document/chunk counts. */
export async function health(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`)
  return unwrap<HealthResponse>(res)
}

/** Upload a document (PDF / image / Office file) into the RAG index. */
export async function ingest(file: File): Promise<IngestResponse> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/ingest`, { method: 'POST', body: form })
  return unwrap<IngestResponse>(res)
}
