"""Embed the question, run the pgvector cosine search, and resolve metadata.

Returns the most relevant chunks (== pages, in v1) with their source document,
page number, raw text, and similarity score.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings, get_settings
from ..db import connection, search_chunks
from ..ingest.embedder import Embedder, get_embedder
from ..logging_config import get_logger

log = get_logger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    filename: str
    source: str | None
    text_pdf_path: str | None
    page_number: int
    content: str
    score: float


def retrieve(
    question: str,
    k: int | None = None,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
) -> list[RetrievedChunk]:
    """Return the top-k chunks most similar to ``question`` (highest score first)."""
    settings = settings or get_settings()
    embedder = embedder or get_embedder()
    k = k or settings.top_k

    query_vec = embedder.encode_query(question)
    with connection(settings) as conn:
        rows = search_chunks(conn, query_vec, k)

    hits = [
        RetrievedChunk(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            filename=r["filename"],
            source=r["source"],
            text_pdf_path=r["text_pdf_path"],
            page_number=r["page_number"],
            content=r["content"],
            score=float(r["score"]),
        )
        for r in rows
    ]
    log.info(
        "Retrieved %d chunk(s) for question %r (top score=%.3f).",
        len(hits),
        question[:60],
        hits[0].score if hits else float("nan"),
    )
    return hits
