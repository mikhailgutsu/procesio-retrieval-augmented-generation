"""Turn answering spans into highlight output.

Two outputs per span:
  * **UI payload** — span text + character offsets within the source page text +
    document/page reference, so a web UI can render the passage highlighted.
  * **PDF annotation (optional)** — locate the span on the source page with
    PyMuPDF ``page.search_for`` and draw a highlight with ``add_highlight_annot``,
    exporting an annotated PDF and a per-page PNG into ``data/highlights/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf as fitz

from ..config import Settings, get_settings
from ..logging_config import get_logger

if TYPE_CHECKING:
    from .extractor import AnswerSpan
    from .retriever import RetrievedChunk

log = get_logger(__name__)


@dataclass
class Highlight:
    document_id: int
    filename: str
    page_number: int
    text: str
    char_start: int | None       # offset within the page/chunk text
    char_end: int | None
    matched_in_chunk: bool        # span found as a substring of the retrieved text
    matched_in_pdf: bool          # span located on the PDF page (search_for)
    annotated_pdf: str | None = None
    page_image: str | None = None


def build_highlights(
    spans: list["AnswerSpan"],
    chunks: list["RetrievedChunk"],
    settings: Settings | None = None,
) -> list[Highlight]:
    """Compute UI offsets for each span and, if enabled, annotate the source PDFs."""
    settings = settings or get_settings()
    settings.ensure_dirs()

    by_key: dict[tuple[int, int], "RetrievedChunk"] = {}
    for c in chunks:
        by_key.setdefault((c.document_id, c.page_number), c)

    highlights: list[Highlight] = []
    for span in spans:
        chunk = by_key.get((span.document_id, span.page_number))
        filename = chunk.filename if chunk else f"document {span.document_id}"
        start = chunk.content.find(span.text) if chunk else -1
        highlights.append(
            Highlight(
                document_id=span.document_id,
                filename=filename,
                page_number=span.page_number,
                text=span.text,
                char_start=start if start != -1 else None,
                char_end=(start + len(span.text)) if start != -1 else None,
                matched_in_chunk=start != -1,
                matched_in_pdf=False,  # set True below if located on the PDF page
            )
        )

    if settings.highlight_pdf:
        _annotate_pdfs(highlights, by_key, settings)
    return highlights


def _annotate_pdfs(
    highlights: list[Highlight],
    by_key: dict[tuple[int, int], "RetrievedChunk"],
    settings: Settings,
) -> None:
    """Draw highlights on each source PDF, grouped by document (one open per doc)."""
    doc_ids = {h.document_id for h in highlights}
    for document_id in doc_ids:
        chunk = next(
            (c for (d, _p), c in by_key.items() if d == document_id), None
        )
        if not chunk or not chunk.text_pdf_path:
            continue
        pdf_path = Path(chunk.text_pdf_path)
        if not pdf_path.exists():
            log.warning("Source PDF missing, skipping annotation: %s", pdf_path)
            continue

        doc_highlights = [h for h in highlights if h.document_id == document_id]
        try:
            with fitz.open(pdf_path) as doc:
                pages_touched: set[int] = set()
                for h in doc_highlights:
                    page = doc[h.page_number - 1]
                    rects = page.search_for(h.text)
                    if rects:
                        for rect in rects:
                            page.add_highlight_annot(rect)
                        h.matched_in_pdf = True
                        pages_touched.add(h.page_number)

                out_pdf = settings.highlights_dir / f"{pdf_path.stem}.highlighted.pdf"
                doc.save(out_pdf, garbage=3, deflate=True)

                page_images: dict[int, str] = {}
                for pno in pages_touched:
                    pix = doc[pno - 1].get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_path = settings.highlights_dir / f"{pdf_path.stem}.p{pno}.png"
                    pix.save(img_path)
                    page_images[pno] = str(img_path)

            for h in doc_highlights:
                if h.matched_in_pdf:
                    h.annotated_pdf = str(out_pdf)
                    h.page_image = page_images.get(h.page_number)
        except Exception as exc:  # annotation is best-effort; never fail the answer
            log.warning("PDF annotation failed for %s: %s", pdf_path.name, exc)
