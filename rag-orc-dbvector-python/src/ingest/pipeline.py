"""Ingestion orchestration — runs steps 1–5 per document.

  1. Load a document (PDF, image, PowerPoint, or Excel) and dedupe by content hash.
  2. Turn it into a text-bearing form (OCR for scans/images; native text for Office).
  3. Extract text per page/slide/sheet and chunk it (1 page = 1 chunk, v1).
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
from .document_loader import is_supported_file, load_document
from .embedder import Embedder, get_embedder

log = get_logger(__name__)


@dataclass
class IngestResult:
    filename: str
    document_id: int | None
    num_pages: int
    num_chunks: int
    was_ocred: bool
    kind: str = ""
    skipped: bool = False
    reason: str = ""
    errors: list[str] = field(default_factory=list)


def compute_file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def ingest_file(
    path: str | Path,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
    chunker: BaseChunker | None = None,
) -> IngestResult:
    """Ingest a single document (PDF/image/pptx/xlsx) end-to-end."""
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

    # 2–3. Load into per-page text (OCR for scans/images, native for Office) and chunk.
    loaded = load_document(path, settings)
    pages = loaded.pages
    num_pages = len(pages)
    chunks = chunker.chunk(pages)
    if not chunks:
        raise RagError(
            f"No non-empty text extracted from {filename}. "
            f"If it is a scan/image, enable OCR / vision fallback."
        )
    log.info(
        "Chunked %s (%s) into %d chunk(s) across %d page(s).",
        filename,
        loaded.kind,
        len(chunks),
        num_pages,
    )

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
            text_pdf_path=loaded.text_pdf_path,
        )
        inserted = insert_chunks(conn, document_id, rows)
        conn.commit()

    log.info("Stored document id=%d with %d chunk(s).", document_id, inserted)
    return IngestResult(
        filename=filename,
        document_id=document_id,
        num_pages=num_pages,
        num_chunks=inserted,
        was_ocred=loaded.was_ocred,
        kind=loaded.kind,
    )


# Backward-compatible alias — ingestion now handles all supported formats.
ingest_pdf = ingest_file


def iter_ingestable(directory: str | Path) -> list[Path]:
    """Return supported files under ``directory`` **recursively** (sorted).

    Case-insensitive by extension; skips unsupported types and macOS archive
    junk (``__MACOSX/`` entries and ``._`` AppleDouble resource-fork files).
    """
    directory = Path(directory)
    return sorted(
        p
        for p in directory.rglob("*")
        if p.is_file()
        and is_supported_file(p)
        and not p.name.startswith("._")
        and "__MACOSX" not in p.parts
    )


def ingest_directory(
    directory: str | Path | None = None,
    settings: Settings | None = None,
) -> list[IngestResult]:
    """Ingest every supported file (PDF/image/pptx/xlsx) under a directory, recursively.

    Default directory is ``DATA_RAW_DIR``. Subfolders are traversed; selection is
    case-insensitive and skips unsupported types (e.g. .txt/.docx/.ppt/.xls) and
    macOS archive junk silently.
    """
    settings = settings or get_settings()
    init_schema(settings)  # idempotent — safe to call before any ingestion
    directory = Path(directory) if directory else settings.raw_dir
    files = iter_ingestable(directory)
    if not files:
        log.warning("No ingestable files (PDF/image/pptx/xlsx) found under %s", directory)
        return []

    embedder = get_embedder()
    chunker = get_chunker(settings)
    results: list[IngestResult] = []
    for f in files:
        try:
            results.append(ingest_file(f, settings, embedder, chunker))
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
