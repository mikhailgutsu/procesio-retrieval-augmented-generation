# RAG POC — Chat Frontend + Dockerized Backend

A small end-to-end demo of a Retrieval-Augmented-Generation stack:

- **Backend** — [`rag-orc-dbvector-python/`](rag-orc-dbvector-python/): a FastAPI service backed by
  Postgres + **pgvector**. It ingests documents (PDF / images / Office / CSV), embeds them, stores
  vectors, and answers questions with **page-level citations** using an LLM
  (**OpenAI `gpt-4o-mini`** by default, Anthropic Claude optional). Runs in **Docker**.
- **Frontend** — [`frontend-ai-poc/`](frontend-ai-poc/): a lightweight **React + Vite + TypeScript**
  chat UI that talks to the backend. Runs **locally** with `yarn`.

```
┌──────────────────────┐        HTTP (CORS)        ┌───────────────────────────────┐
│  frontend-ai-poc     │  ───────────────────────► │  rag_app  (FastAPI :8000)     │
│  React + Vite :5173  │   POST /ask   /ingest     │   embed → pgvector → LLM      │
│  (chat UI, local)    │   GET  /health            │        (gpt-4o-mini)          │
└──────────────────────┘                           │            │                  │
                                                    │            ▼                  │
                                                    │  rag_pgvector (Postgres :5432)│
                                                    └───────────────────────────────┘
             (both run via Docker Compose profile "app")
```

---

## The RAG endpoints (backend)

Defined in [`rag-orc-dbvector-python/api/main.py`](rag-orc-dbvector-python/api/main.py):

| Method & path  | Purpose                                                    | Body / params                                                      |
| -------------- | ---------------------------------------------------------- | ------------------------------------------------------------------ |
| `GET /health`  | Liveness + DB connectivity + document/chunk counts         | —                                                                  |
| `POST /ingest` | Ingest a document into the vector index                    | `multipart/form-data`: `file` (upload) **or** `path` (server-side) |
| `POST /ask`    | **The main RAG flow** — embed → vector search → LLM answer | JSON `{ "question": "...", "k": 5, "highlight": true }`            |

**`POST /ask` is the endpoint the chat uses.** Its response shape (rendered by the frontend):

```jsonc
{
  "question": "…",
  "answerable": true,
  "answer": "grounded answer text",
  "citations":  [{ "document_id": 1, "filename": "spec.pdf", "page_number": 3, "score": 0.82 }],
  "retrieved":  [{ "document_id": 1, "filename": "spec.pdf", "page_number": 3, "score": 0.82, "preview": "…" }],
  "highlights": [{ "text": "verbatim span", "page_number": 3, "matched_in_pdf": true, ... }]
}
```

The flow (see `src/query/pipeline.py`): the question is embedded with the same model used at ingestion,
matched against pgvector (top-`k` cosine), then the LLM extracts a grounded answer + verbatim spans for
citations/highlighting.

---

## 🔑 Where the ChatGPT (gpt-4o-mini) token goes

The backend is **provider-agnostic** (`src/llm.py`). To use ChatGPT for the `/ask` answer step you set
**three** things — the provider, the model, and your key — all via environment variables read from
[`rag-orc-dbvector-python/.env`](rag-orc-dbvector-python/.env):

```dotenv
LLM_PROVIDER=openai          # use ChatGPT for answer extraction
OPENAI_MODEL=gpt-4o-mini     # the model
OPENAI_API_KEY=sk-...        # ← paste your OpenAI API key here
```

- Get a key at <https://platform.openai.com/api-keys> (starts with `sk-`).
- These are already the defaults in `.env.example`; only `OPENAI_API_KEY` is empty and must be filled in.
- **Docker:** [`docker-compose.yml`](rag-orc-dbvector-python/docker-compose.yml) forwards
  `LLM_PROVIDER`, `OPENAI_MODEL`, and `OPENAI_API_KEY` into the `app` container. Compose reads them from
  `rag-orc-dbvector-python/.env`, so putting the key there is enough for both local and Docker runs.
- Prefer Claude instead? Set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...`.

> The key lives **only in the backend**. The React frontend never sees it — it only calls the backend's
> HTTP endpoints.

---

## Prerequisites

- **Docker** + Docker Compose (backend)
- **Node ≥ 20** and **Yarn** (frontend)
- An **OpenAI API key** for `gpt-4o-mini`

## Quick start

```bash
# 1. One-time setup: create .env files + install frontend deps
make setup

# 2. Paste your key into rag-orc-dbvector-python/.env  (OPENAI_API_KEY=sk-...)

# 3. Start the backend (Postgres + API) in Docker
make up            # → API on http://localhost:8000

# 4. (optional) ingest documents: drop files in rag-orc-dbvector-python/data/raw/ then
make ingest        # …or just use the "＋ Upload doc" button in the UI

# 5. Start the chat frontend locally
make fe            # → UI on http://localhost:5173
```

Open <http://localhost:5173>, upload a document (or `make ingest`), and start asking questions.

`make dev` does steps 3 + 5 together (backend detached in Docker, then the frontend in the foreground).

## Make targets

Run `make help` for the full list. The essentials:

| Command                 | What it does                                                    |
| ----------------------- | --------------------------------------------------------------- |
| `make setup`            | Create `.env` files from examples + `yarn install` the frontend |
| `make up` / `make down` | Start / stop the Dockerized backend (db + api)                  |
| `make logs`             | Follow the API container logs                                   |
| `make ingest`           | Ingest everything in `data/raw/` (inside the container)         |
| `make fe`               | Run the Vite chat UI locally (`:5173`)                          |
| `make fe-build`         | Production build of the frontend                                |
| `make dev`              | Backend (Docker, detached) + frontend (local)                   |
| `make clean`            | Stop backend + delete the frontend `dist/`                      |

## Manual commands (without Make)

```bash
# Backend in Docker
cd rag-orc-dbvector-python
cp .env.example .env            # then edit OPENAI_API_KEY
docker compose --profile app up --build -d

# Frontend locally
cd frontend-ai-poc
cp .env.example .env            # VITE_API_BASE defaults to http://localhost:8000
yarn install
yarn dev
```

## How the frontend reaches the backend

The frontend calls the backend directly at `VITE_API_BASE`
(default `http://localhost:8000`, see [`frontend-ai-poc/.env.example`](frontend-ai-poc/.env.example)).
Cross-origin browser calls are allowed by the backend's CORS middleware
(`CORS_ALLOW_ORIGINS`, default `*` for this POC). To point the UI at a different backend host/port,
change `VITE_API_BASE` and restart `yarn dev`.

## Troubleshooting

- **`/ask` returns 503 / "OPENAI_API_KEY is not set"** → the key is missing in
  `rag-orc-dbvector-python/.env`; add it and `make rebuild`.
- **Health badge shows "DB offline"** → the database container isn't up yet; `make up` (or `make db-up`)
  and wait for the healthcheck.
- **"No relevant pages were found"** → nothing is ingested yet; upload a document or run `make ingest`.
- **CORS errors in the browser console** → confirm `CORS_ALLOW_ORIGINS` in the backend `.env` and that
  `VITE_API_BASE` points at the running API.
