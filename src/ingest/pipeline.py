"""Ingestion orchestration — runs steps 1–5 per document.

  1. Load PDF (and dedupe by content hash).
  2. Detect scanned/image PDFs and OCR them → text-bearing PDF.
  3. Extract text page-by-page and chunk it (1 page = 1 chunk, v1).
  4. Embed each chunk with the shared embedder.
  5. Persist document + chunks (steps 4 & 5 in the same transaction).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings, get_settings
from ..db import (
    connection,
    delete_document,
    find_document_by_hash,
    init_schema,
    insert_chunks,
    insert_document,
)
from ..errors import RagError
from ..logging_config import get_logger
from .chunker import BaseChunker, get_chunker
from .embedder import Embedder, get_embedder
from .pdf_loader import (
    ensure_text_pdf,
    extract_pages_text,
    is_supported_file,
    render_page_png,
    vision_transcribe_page,
)

log = get_logger(__name__)


@dataclass
class IngestResult:
    filename: str
    document_id: int | None
    num_pages: int
    num_chunks: int
    was_ocred: bool
    skipped: bool = False
    reason: str = ""
    errors: list[str] = field(default_factory=list)


def compute_file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _maybe_vision_fill(
    text_pdf: Path, pages: list[str], was_ocred: bool, settings: Settings
) -> list[str]:
    """Optionally transcribe pages still empty after OCR using a Claude vision call."""
    if not (was_ocred and settings.ocr_vision_fallback):
        return pages
    filled = list(pages)
    for i, text in enumerate(pages):
        if len(text.strip()) < settings.scanned_char_threshold:
            log.info("Vision fallback on page %d of %s", i + 1, text_pdf.name)
            png = render_page_png(text_pdf, i)
            transcribed = vision_transcribe_page(png, settings)
            if transcribed:
                filled[i] = transcribed
    return filled


def ingest_pdf(
    path: str | Path,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
    chunker: BaseChunker | None = None,
) -> IngestResult:
    """Ingest a single PDF end-to-end. Returns an :class:`IngestResult`."""
    settings = settings or get_settings()
    embedder = embedder or get_embedder()
    chunker = chunker or get_chunker(settings)
    settings.ensure_dirs()

    path = Path(path)
    if not path.exists():
        raise RagError(f"File not found: {path}")
    filename = path.name
    log.info("── Ingesting %s ──", filename)

    # 1. Dedupe by content hash.
    content_hash = compute_file_hash(path)
    replace_existing_id: int | None = None
    with connection(settings) as conn:
        existing = find_document_by_hash(conn, content_hash)
    if existing:
        if settings.ingest_on_duplicate == "skip":
            log.info("Skip: %s already ingested as document id=%s.", filename, existing["id"])
            return IngestResult(
                filename=filename,
                document_id=existing["id"],
                num_pages=existing["num_pages"] or 0,
                num_chunks=0,
                was_ocred=False,
                skipped=True,
                reason="duplicate content hash",
            )
        replace_existing_id = existing["id"]
        log.info("Replace: re-ingesting %s (was document id=%s).", filename, existing["id"])

    # 2. Ensure a text-bearing PDF (OCR if scanned).
    text_pdf, was_ocred = ensure_text_pdf(path, settings)

    # 3. Extract per-page text (+ optional vision fallback) and chunk it.
    pages = extract_pages_text(text_pdf)
    pages = _maybe_vision_fill(text_pdf, pages, was_ocred, settings)
    num_pages = len(pages)
    chunks = chunker.chunk(pages)
    if not chunks:
        raise RagError(
            f"No non-empty text extracted from {filename}. "
            f"If it is a scan, enable OCR / vision fallback."
        )
    log.info("Chunked %s into %d chunk(s) across %d page(s).", filename, len(chunks), num_pages)

    # 4. Embed all chunk contents with the shared embedder.
    embeddings = embedder.encode_passages([c.content for c in chunks])
    log.info("Embedded %d chunk(s) (dim=%d).", len(chunks), embedder.dimension)

    # 5. Persist document + chunks in a single transaction.
    rows = [(c.page_number, c.content, embeddings[i]) for i, c in enumerate(chunks)]
    with connection(settings) as conn:
        if replace_existing_id is not None:
            delete_document(conn, replace_existing_id)
        document_id = insert_document(
            conn,
            filename=filename,
            source=str(path),
            num_pages=num_pages,
            content_hash=content_hash,
            text_pdf_path=str(text_pdf),
        )
        inserted = insert_chunks(conn, document_id, rows)
        conn.commit()

    log.info("Stored document id=%d with %d chunk(s).", document_id, inserted)
    return IngestResult(
        filename=filename,
        document_id=document_id,
        num_pages=num_pages,
        num_chunks=inserted,
        was_ocred=was_ocred,
    )


def ingest_directory(
    directory: str | Path | None = None,
    settings: Settings | None = None,
) -> list[IngestResult]:
    """Ingest every supported file (PDF or image) in a directory.

    Default directory is ``DATA_RAW_DIR``. Selection is case-insensitive and
    skips unsupported types (e.g. .txt/.docx) silently.
    """
    settings = settings or get_settings()
    init_schema(settings)  # idempotent — safe to call before any ingestion
    directory = Path(directory) if directory else settings.raw_dir
    files = sorted(p for p in directory.iterdir() if p.is_file() and is_supported_file(p))
    if not files:
        log.warning("No ingestable files (PDF/image) found in %s", directory)
        return []

    embedder = get_embedder()
    chunker = get_chunker(settings)
    results: list[IngestResult] = []
    for f in files:
        try:
            results.append(ingest_pdf(f, settings, embedder, chunker))
        except RagError as exc:
            log.error("Failed to ingest %s: %s", f.name, exc)
            results.append(
                IngestResult(
                    filename=f.name,
                    document_id=None,
                    num_pages=0,
                    num_chunks=0,
                    was_ocred=False,
                    skipped=True,
                    reason="error",
                    errors=[str(exc)],
                )
            )
    return results
