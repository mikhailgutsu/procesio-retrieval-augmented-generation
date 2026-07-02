# RAG Technical Documentation Assistant

A Retrieval-Augmented Generation system that ingests technical PDF documentation,
stores it as searchable vector embeddings, and answers natural-language questions
by retrieving the most relevant pages, extracting the answering passages with an
LLM (Anthropic Claude), and highlighting them.

Built for the _AI Operations Assistant for Electrical Substations_ PoC
(see [`spec/ai-substation-assistant-poc.md`](spec/ai-substation-assistant-poc.md)):
source documents may be in technical Romanian, so the embedding model is
multilingual and answers cite the exact source document + page.

---

## Architecture

Two independent pipelines share one PostgreSQL + `pgvector` database.

```
INGESTION (src/ingest)                     RETRIEVAL (src/query)
  PDF in data/raw/                           question (text)
     │                                          │
     ▼                                          ▼
  scanned? ──yes──► OCR (ocrmypdf) ──┐       embed question (same embedder)
     │no                             │          │
     ▼                               ▼          ▼
  extract text per page ◄────────────┘       pgvector top-k cosine search
     │                                          │
     ▼                                          ▼
  chunk (1 page = 1 chunk, v1)               resolve metadata (doc, page, score)
     │                                          │
     ▼                                          ▼
  embed each chunk (multilingual e5)         LLM extracts verbatim answering spans
     │                                          │
     ▼                                          ▼
  store vector + metadata in pgvector        highlight spans (UI payload + PDF annot.)
```

The **embedder is shared** by both pipelines (`src/ingest/embedder.py`) so the
query is embedded identically to the stored passages.

### Layout

```
.
├── docker-compose.yml         # pgvector/pgvector:pg16 (+ optional app container)
├── Dockerfile                 # optional app image (Python 3.12 + OCR toolchain)
├── requirements.txt
├── .env.example               # copy to .env
├── Makefile                   # install / db-up / ingest / ask / api / test
├── main.py                    # thin wrapper over src.cli
├── data/{raw,processed,highlights}/
├── src/
│   ├── config.py              # env-driven settings (pydantic-settings)
│   ├── db.py                  # pool, idempotent schema, insert/search SQL
│   ├── errors.py              # typed exceptions per pipeline stage
│   ├── cli.py                 # init-db / ingest / ask / stats / reset-db
│   ├── ingest/{document_loader,pdf_loader,chunker,embedder,pipeline}.py
│   └── query/{retriever,extractor,highlighter,pipeline}.py
├── api/main.py                # FastAPI: POST /ingest, POST /ask, GET /health
├── scripts/make_sample_pdf.py # generates a demo Romanian PDF into data/raw/
└── tests/
```

---

## Prerequisites

- **Python 3.11–3.13** (this repo is set up on 3.12). `torch`/`ocrmypdf` wheels
  are not yet published for 3.14, so do **not** use 3.14.
- **Docker** + **Docker Compose** (for the database).
- **For OCR only** (scanned PDFs): **Tesseract** with the language packs you need
  (`ron`, `eng`) and **Ghostscript**. Not required for born-digital PDFs.
  - macOS: `brew install tesseract tesseract-lang ghostscript`
  - Debian/Ubuntu: `apt-get install tesseract-ocr tesseract-ocr-ron ghostscript`
  - Or just run the app in Docker (`--profile app`), where these are pre-installed.
- **An Anthropic API key** for the answer-extraction step (`/ask`). Retrieval and
  ingestion work without it.

---

## Setup

```bash
# 1. Create the virtualenv (Python 3.12) and install dependencies
make install                 # == python3.12 -m venv .venv && pip install -r requirements.txt

# 2. Configure
cp .env.example .env
#   edit .env → set ANTHROPIC_API_KEY (needed only for the /ask LLM step)

# 3. Start Postgres + pgvector
make db-up                   # docker compose up -d db

# 4. Initialise the schema (also done automatically on first ingest / API start)
make init-db
```

The schema (`documents`, `chunks`, HNSW cosine index) is created idempotently.
The `chunks.embedding` vector dimension is written from `EMBEDDING_DIM`.

---

## Usage

### Ingest

```bash
# Generate a demo PDF (technical Romanian) to try things out
.venv/bin/python scripts/make_sample_pdf.py

# Ingest every PDF/image in data/raw/
make ingest                              # == python -m src.cli ingest
# …or a single file
.venv/bin/python -m src.cli ingest --path data/raw/statie_110kV_instructiuni.pdf
```

Supported inputs:
- **PDF** and **images** (`.png/.jpg/.jpeg/.tif/.tiff/.bmp/.webp`) — scans/images are
  OCR'd automatically into a text-layer PDF (requires Tesseract + Ghostscript). With
  `OCR_VISION_FALLBACK=true` + an Anthropic key, diagrams/photos that OCR can't read are
  transcribed and described by Claude vision so they become searchable.
- **PowerPoint** `.pptx` (1 slide = 1 page) · **Excel** `.xlsx/.xlsm/.xls` (1 sheet = 1 page).
- **Word** `.docx/.doc` and **CSV** — paginated into ~text blocks (these formats have no
  native pages). Legacy `.doc` needs a converter on the host (`textutil` on macOS is
  built-in; `antiword` or LibreOffice on Linux — the app container ships `antiword`).

Legacy `.ppt`, archives (`.rar/.zip`), video, and other types are skipped silently;
extract archives and convert `.ppt` first.

To make diagrams/photos that OCR can't read searchable, enable the vision fallback —
see [VISION_FALLBACK.md](VISION_FALLBACK.md) (e.g. with a cheap OpenAI `gpt-4o-mini` key).

The first ingest downloads the embedding model (~1 GB for `multilingual-e5-base`).
Re-ingesting the same file is a no-op (deduped by content hash;
set `INGEST_ON_DUPLICATE=replace` to overwrite).

### Ask

```bash
# Full answer with LLM extraction + citations + highlights (needs ANTHROPIC_API_KEY)
make ask q="Ce EIP este necesar înainte de manevre?"
# machine-readable output
.venv/bin/python -m src.cli ask "Ce verificări se fac înainte de reanclanșare?" --json

# Retrieval only — no API key required; verify relevance before adding the LLM
.venv/bin/python -m src.cli ask "punere la pământ" --retrieve-only
```

`ask` prints the grounded answer, the source citations (**document + page** with
similarity score), and the verbatim highlight spans. When `HIGHLIGHT_PDF=true`,
an annotated PDF and per-page PNGs are written to `data/highlights/`.

### API

```bash
make api                                 # uvicorn api.main:app on :8000
```

- `GET  /health` — liveness + DB connectivity + document/chunk counts
- `POST /ingest` — multipart file upload (PDF or image), **or** JSON/form `path` to a server-side file
- `POST /ask` — `{"question": "...", "k": 5, "highlight": true}` → answer + citations + highlights

```bash
# ingest an upload
curl -F "file=@data/raw/statie_110kV_instructiuni.pdf" http://localhost:8000/ingest
# ask
curl -X POST http://localhost:8000/ask \
     -H 'content-type: application/json' \
     -d '{"question":"Ce EIP este necesar înainte de manevre?"}'
```

Interactive docs at `http://localhost:8000/docs`.

---

## Configuration

All configuration is environment-driven (`.env`). Key settings:

| Variable                                              | Default                                   | Purpose                                                    |
| ----------------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------- |
| `DATABASE_URL`                                        | `postgresql://rag:rag@localhost:5432/rag` | Postgres/pgvector connection                               |
| `EMBEDDING_MODEL`                                     | `intfloat/multilingual-e5-base`           | sentence-transformers model                                |
| `EMBEDDING_DIM`                                       | `768`                                     | Must match the model **and** the `chunks` vector column    |
| `EMBEDDING_QUERY_PREFIX` / `EMBEDDING_PASSAGE_PREFIX` | `query:` / `passage:`                     | e5 instruction prefixes (empty for MiniLM)                 |
| `TOP_K`                                               | `5`                                       | Chunks retrieved per question                              |
| `LLM_PROVIDER`                                        | `anthropic`                               | Answer-extraction provider: `anthropic` or `openai`        |
| `VISION_PROVIDER`                                     | — (inherits `LLM_PROVIDER`)               | Vision-fallback provider: `anthropic` / `openai`           |
| `ANTHROPIC_MODEL` / `ANTHROPIC_API_KEY`               | `claude-opus-4-8` / —                     | Claude model + key (needed for `/ask` when provider=anthropic) |
| `OPENAI_MODEL` / `OPENAI_API_KEY`                     | `gpt-4o-mini` / —                         | OpenAI model + key (used when a provider = `openai`)       |
| `SCANNED_CHAR_THRESHOLD` / `SCANNED_PAGE_RATIO`       | `100` / `0.5`                             | Scanned-detection thresholds                               |
| `OCR_LANGUAGES`                                       | `ron+eng`                                 | Tesseract language packs                                   |
| `OCR_VISION_FALLBACK`                                 | `false`                                   | Describe unreadable diagrams/photos — see [VISION_FALLBACK.md](VISION_FALLBACK.md) |
| `CHUNK_STRATEGY`                                      | `page`                                    | `page` (1 page = 1 chunk) or `window` (fixed char windows) |
| `INGEST_ON_DUPLICATE`                                 | `skip`                                    | `skip` or `replace` on re-ingest of the same file          |
| `HIGHLIGHT_PDF`                                       | `true`                                    | Also emit annotated PDF/PNG per span                       |

**Changing the embedding model** to one with a different dimension: set
`EMBEDDING_MODEL` + `EMBEDDING_DIM`, then re-create the table (`make db-reset`) —
no code changes needed. A dimension mismatch fails loudly at schema-init /
model-load time.

---

## Data model

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id            SERIAL PRIMARY KEY,
    filename      TEXT NOT NULL,
    source        TEXT,
    num_pages     INTEGER,
    content_hash  TEXT UNIQUE,          -- sha256 of the file, for idempotent re-ingest
    text_pdf_path TEXT,                 -- text-bearing PDF used for extraction/highlighting
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE chunks (
    id           SERIAL PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number  INTEGER NOT NULL,
    content      TEXT NOT NULL,
    embedding    VECTOR(768) NOT NULL,  -- dimension = EMBEDDING_DIM
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
```

`content_hash` and `text_pdf_path` extend the base spec to support idempotent
re-ingest and PDF highlighting, respectively.

---

## Tests

```bash
make test                    # == python -m pytest
```

Coverage:

- **`test_pdf_loader.py`** — scanned-vs-text detection + per-page extraction.
- **`test_chunker.py`** — chunk creation (page strategy + fixed-window).
- **`test_embedder.py`** — embedding dimension enforcement + instruction prefixes.
- **`test_extractor.py`** — LLM extraction parsing, verbatim spans, dropping
  hallucinated citations (fake client — no network).
- **`test_retrieval.py`** — _(integration)_ round-trip retrieval on a seeded
  dataset + metadata resolution. Uses a deterministic offline embedder, so no
  model download or network. Skipped automatically if Postgres isn't running.

Unit tests need neither the DB nor a network. Integration tests need `make db-up`.

---

## Run everything in Docker (optional)

```bash
docker compose --profile app up --build
# db + app (with Tesseract/Ghostscript preinstalled); API on http://localhost:8000
# pass your key:  ANTHROPIC_API_KEY=sk-ant-... docker compose --profile app up --build
```

---

## Notes & limitations (PoC)

- v1 chunking = 1 page per chunk; the chunker is pluggable (`CHUNK_STRATEGY=window`).
- The LLM is instructed to return **verbatim** spans; highlighting locates them on
  the page with `page.search_for`. Multi-line spans may not always match in the PDF
  (the UI character offsets still resolve) — this is best-effort by design.
- Inputs: PDF, images (png/jpg/jpeg/tiff/bmp/webp), PowerPoint (.pptx), Excel
  (.xlsx/.xlsm/.xls), Word (.docx), CSV. Images are OCR'd like scanned PDFs; PowerPoint
  maps 1 slide → 1 page, Excel 1 sheet → 1 page, and Word/CSV are paginated into text
  blocks. Non-PDF sources have no source PDF, so highlighting is UI-offset only (no PDF
  annotation) — citations by slide/sheet/block still resolve.
- OCR requires Tesseract (with the `OCR_LANGUAGES` packs, e.g. `ron`) + Ghostscript
  on the host (or use the app container). A missing language pack fails that file
  with a clear error and continues with the rest.
- No authentication on the API — this is a PoC; add auth before any real deployment.
