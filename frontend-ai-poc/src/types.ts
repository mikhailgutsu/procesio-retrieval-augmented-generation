// Types mirroring the RAG backend responses (see api/main.py + src/query/pipeline.py).

export interface Citation {
  document_id: number
  filename: string
  page_number: number
  score: number
}

export interface RetrievedChunk {
  document_id: number
  filename: string
  page_number: number
  score: number
  preview: string
}

export interface Highlight {
  document_id: number
  filename: string
  page_number: number
  text: string
  char_start: number | null
  char_end: number | null
  matched_in_chunk: boolean
  matched_in_pdf: boolean
  annotated_pdf: string | null
  page_image: string | null
}

/** Response of `POST /ask`. */
export interface AskResponse {
  question: string
  answerable: boolean
  answer: string
  citations: Citation[]
  highlights: Highlight[]
  retrieved: RetrievedChunk[]
}

/** Response of `GET /health`. */
export interface HealthResponse {
  status: string
  database: string
  documents?: number
  chunks?: number
  detail?: string
}

/** Response of `POST /ingest` (backend returns the IngestResult dataclass). */
export interface IngestResponse {
  filename?: string
  document_id?: number
  pages?: number
  chunks?: number
  status?: string
  [key: string]: unknown
}

/** Response of `GET /documents/{id}/text` — the text the RAG pipeline indexed. */
export interface DocumentText {
  document_id: number
  filename: string
  num_pages: number | null
  pages: { page_number: number; content: string }[]
  text: string
}

export type Role = 'user' | 'assistant'

/** A single message rendered in the chat transcript. */
export interface ChatMessage {
  id: string
  role: Role
  text: string
  pending?: boolean
  error?: boolean
  answerable?: boolean
  citations?: Citation[]
  retrieved?: RetrievedChunk[]
  highlights?: Highlight[]
}
