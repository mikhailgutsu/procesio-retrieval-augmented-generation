// Thin client for the RAG FastAPI backend.
//
// The base URL is read from VITE_API_BASE (see .env.example) and defaults to the
// Docker-exposed backend at http://localhost:8000. CORS is enabled server-side.

import type { AskResponse, HealthResponse, IngestResponse } from './types.ts'

const BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/+$/, '')

export function apiBase(): string {
  return BASE
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
