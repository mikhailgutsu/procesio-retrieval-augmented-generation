"""FastAPI application.

Endpoints:
  * ``GET  /health``                     — liveness + DB connectivity + counts.
  * ``POST /ingest``                     — ingest a PDF (multipart upload / path).
  * ``POST /ask``                        — answer a question with citations.
  * ``GET  /documents/{id}/download``    — download the original source file.

Run with:  uvicorn api.main:app --reload
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.config import get_settings
from src.errors import ConfigError, RagError
from src.logging_config import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_dirs()
    try:
        from src.db import init_schema

        init_schema(settings)
    except Exception as exc:  
        log.error("Schema init failed at startup (is the DB up?): %s", exc)
    yield
    from src.db import close_pool

    close_pool()


app = FastAPI(title="RAG Technical Documentation Assistant", version="0.1.0", lifespan=lifespan)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allow the browser frontend (Vite dev server / built SPA) to call this API.
# Set CORS_ALLOW_ORIGINS to a comma-separated list to restrict; defaults to "*".
_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ──────────────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    k: int | None = None
    highlight: bool = True


class IngestPathRequest(BaseModel):
    path: str


# ── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/")
def root() -> dict:
    return {
        "name": app.title,
        "version": app.version,
        "endpoints": ["/health", "/ingest", "/ask", "/documents/{id}/download"],
    }


@app.get("/health")
def health() -> dict:
    from src.db import connection, counts

    try:
        with connection() as conn:
            c = counts(conn)
        return {"status": "ok", "database": "connected", **c}
    except Exception as exc:
        return {"status": "degraded", "database": "unavailable", "detail": str(exc)}


@app.post("/ingest")
def ingest(
    file: UploadFile | None = File(default=None),
    path: str | None = Form(default=None),
) -> dict:
    """Ingest a PDF, image, or Office file (multipart upload or server-side path)."""
    from src.ingest.document_loader import is_supported_file
    from src.ingest.pipeline import ingest_file

    settings = get_settings()
    settings.ensure_dirs()

    if file is not None:
        if not file.filename or not is_supported_file(file.filename):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported file type. Allowed: PDF, image "
                    "(png/jpg/jpeg/tiff/bmp/webp), PowerPoint (.pptx), "
                    "Excel (.xlsx/.xlsm/.xls), Word (.docx/.doc), CSV."
                ),
            )
        target = settings.raw_dir / Path(file.filename).name
        target.write_bytes(file.file.read())
        pdf_path: str | Path = target
    elif path:
        pdf_path = path
        if not Path(pdf_path).exists():
            raise HTTPException(status_code=400, detail=f"Path not found: {pdf_path}")
    else:
        raise HTTPException(status_code=400, detail="Provide a file upload or a 'path' field.")

    try:
        result = ingest_file(pdf_path)
    except RagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.__dict__


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    """Answer a question with source citations and highlight payload."""
    from src.query.pipeline import answer_question

    try:
        result = answer_question(req.question, k=req.k, do_highlight=req.highlight)
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RagError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.to_dict()


@app.get("/documents/{document_id}/download")
def download_document(document_id: int) -> FileResponse:
    """Return the original source file for a document (as an attachment).

    Files are served from the raw data directory by their stored basename; if the
    raw copy is gone we fall back to the recorded source path. Only the basename is
    used to build the path, so this cannot traverse outside the data directory.
    """
    from src.db import connection, get_document

    settings = get_settings()
    with connection() as conn:
        doc = get_document(conn, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    filename = Path(doc["filename"]).name
    candidate = settings.raw_dir / filename
    if not candidate.exists() and doc.get("source"):
        source = Path(str(doc["source"]))
        if source.is_file():
            candidate = source

    if not candidate.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"The source file for document {document_id} is no longer available.",
        )
    return FileResponse(path=candidate, filename=filename)
