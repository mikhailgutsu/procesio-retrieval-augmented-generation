"""FastAPI application.

Endpoints:
  * ``GET  /health``  — liveness + DB connectivity + document/chunk counts.
  * ``POST /ingest``  — ingest a PDF (multipart upload, or a server-side path).
  * ``POST /ask``     — answer a question with citations + highlight payload.

Run with:  uvicorn api.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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
    except Exception as exc:  # keep the app up so /health can report the problem
        log.error("Schema init failed at startup (is the DB up?): %s", exc)
    yield
    from src.db import close_pool

    close_pool()


app = FastAPI(title="RAG Technical Documentation Assistant", version="0.1.0", lifespan=lifespan)


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
    return {"name": app.title, "version": app.version, "endpoints": ["/health", "/ingest", "/ask"]}


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
    """Ingest a PDF supplied either as a multipart upload or a server-side path."""
    from src.ingest.pipeline import ingest_pdf

    settings = get_settings()
    settings.ensure_dirs()

    if file is not None:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only .pdf uploads are supported.")
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
        result = ingest_pdf(pdf_path)
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
