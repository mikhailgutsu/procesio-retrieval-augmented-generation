"""PDF loading: per-page text extraction, scanned-detection, OCR, and (optional)
vision-LLM transcription of pages that remain empty after OCR.

Downstream steps always operate on a text-bearing PDF: for born-digital PDFs
that is the original file; for scanned/image PDFs it is an OCR'd copy written to
``data/processed/``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz

from ..config import Settings, get_settings
from ..errors import OcrError
from ..logging_config import get_logger

log = get_logger(__name__)

# Image inputs are OCR'd like scanned PDFs. A PDF is text-first; anything here is
# an image that gets embedded into a 1-page PDF and then OCR'd. The aggregate set
# of ingestable types (incl. office formats) lives in `document_loader`.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class ScanDetection:
    is_scanned: bool
    num_pages: int
    empty_pages: int
    total_chars: int

    @property
    def empty_ratio(self) -> float:
        return self.empty_pages / self.num_pages if self.num_pages else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Text extraction
# ─────────────────────────────────────────────────────────────────────────────
def sanitize_text(text: str) -> str:
    """Strip characters PostgreSQL text columns can't store.

    NUL (0x00) bytes — emitted by some PDFs for unmapped glyphs — break inserts;
    also drop other C0 control chars except tab/newline/carriage-return.
    """
    if "\x00" in text:
        text = text.replace("\x00", "")
    return "".join(c for c in text if c >= " " or c in "\t\n\r")


def extract_pages_text(pdf_path: str | Path) -> list[str]:
    """Return the extractable text of each page (index 0 == page 1)."""
    pages: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            pages.append(sanitize_text(page.get_text("text")))
    return pages


# ─────────────────────────────────────────────────────────────────────────────
# Scanned detection
# ─────────────────────────────────────────────────────────────────────────────
def detect_scanned(
    pages_text: list[str],
    char_threshold: int,
    page_ratio: float,
) -> ScanDetection:
    """Decide whether a document is scanned/image-only.

    A page with fewer than ``char_threshold`` non-whitespace characters counts
    as having "no text". If at least ``page_ratio`` of pages have no text, the
    whole document is treated as scanned and routed through OCR.
    """
    num_pages = len(pages_text)
    empty = sum(1 for t in pages_text if len(t.strip()) < char_threshold)
    total_chars = sum(len(t.strip()) for t in pages_text)
    is_scanned = num_pages > 0 and (empty / num_pages) >= page_ratio
    return ScanDetection(
        is_scanned=is_scanned,
        num_pages=num_pages,
        empty_pages=empty,
        total_chars=total_chars,
    )


def is_scanned_pdf(pdf_path: str | Path, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    pages = extract_pages_text(pdf_path)
    return detect_scanned(
        pages, settings.scanned_char_threshold, settings.scanned_page_ratio
    ).is_scanned


# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────
def run_ocr(src: Path, out: Path, languages: str) -> Path:
    """Produce a searchable text-layer PDF with ocrmypdf. Raises OcrError on failure.

    Requires Tesseract (with the relevant language packs) and Ghostscript to be
    installed on the system.
    """
    try:
        import ocrmypdf
    except ImportError as exc:  # pragma: no cover - dependency guaranteed by requirements
        raise OcrError("ocrmypdf is not installed") from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    log.info("OCR: %s → %s (lang=%s)", src.name, out.name, languages)
    try:
        ocrmypdf.ocr(
            str(src),
            str(out),
            language=languages,
            force_ocr=True,       # source has little/no text — rasterize & OCR every page
            output_type="pdf",    # avoid PDF/A conversion to reduce external requirements
            optimize=0,
            progress_bar=False,
        )
    except Exception as exc:  # ocrmypdf raises several exception types
        raise OcrError(
            f"OCR failed for {src.name}: {exc}. Ensure Tesseract "
            f"(packs: {languages}) and Ghostscript are installed."
        ) from exc
    return out


def image_to_pdf(image_path: str | Path, settings: Settings | None = None) -> Path:
    """Embed an image into a single-page PDF (no text layer) in ``data/processed/``.

    The result has no extractable text, so the normal scanned-detection path will
    route it through OCR — no special-casing needed downstream.
    """
    settings = settings or get_settings()
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    image_path = Path(image_path)
    out = settings.processed_dir / f"{image_path.stem}.image.pdf"
    with fitz.open(image_path) as img:
        pdf_bytes = img.convert_to_pdf()
    with fitz.open("pdf", pdf_bytes) as pdf:
        pdf.save(out)
    log.info("Converted image %s → %s", image_path.name, out.name)
    return out


def ensure_text_pdf(input_path: str | Path, settings: Settings | None = None) -> tuple[Path, bool]:
    """Return a (text_bearing_pdf_path, was_ocred) pair.

    * Born-digital PDFs are returned unchanged.
    * Scanned PDFs and image inputs (png/jpg/tiff/…) are OCR'd into
      ``data/processed/<stem>.ocr.pdf``.
    """
    settings = settings or get_settings()
    input_path = Path(input_path)

    # An image is embedded into a PDF first; that PDF has no text → detected as scanned.
    if input_path.suffix.lower() in IMAGE_SUFFIXES:
        source_pdf = image_to_pdf(input_path, settings)
    else:
        source_pdf = input_path

    pages = extract_pages_text(source_pdf)
    detection = detect_scanned(
        pages, settings.scanned_char_threshold, settings.scanned_page_ratio
    )
    log.info(
        "Scan check: %s — %d pages, %d empty (%.0f%%) → %s",
        input_path.name,
        detection.num_pages,
        detection.empty_pages,
        detection.empty_ratio * 100,
        "SCANNED/OCR" if detection.is_scanned else "text",
    )
    if not detection.is_scanned:
        return source_pdf, False

    out = settings.processed_dir / f"{input_path.stem}.ocr.pdf"
    run_ocr(source_pdf, out, settings.ocr_languages)
    return out, True


# ─────────────────────────────────────────────────────────────────────────────
# Optional vision-LLM fallback for pages still empty after OCR
# ─────────────────────────────────────────────────────────────────────────────
def render_page_png(pdf_path: str | Path, page_index: int, zoom: float = 2.0) -> bytes:
    """Render a single page to PNG bytes (for a vision-LLM transcription fallback)."""
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png")


def vision_transcribe_page(png_bytes: bytes, settings: Settings | None = None) -> str:
    """Transcribe a page image with Claude vision. Returns '' on any failure."""
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        log.warning("Vision fallback requested but ANTHROPIC_API_KEY is unset; skipping.")
        return ""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "This is a page or image from technical substation documentation "
                                "(a scan, a single-line/monofilar diagram, an equipment photo, or a "
                                "schematic). First, transcribe ALL visible text verbatim, preserving "
                                "reading order — labels, bay/cell names, equipment tags, values and "
                                "units. Then, if it is a diagram or photo, add a short factual "
                                "description of what it shows (equipment, connections, identifiers) so "
                                "it can be found by search. Respond in the document's language. "
                                "Return only the transcription and description, no preamble."
                            ),
                        },
                    ],
                }
            ],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as exc:  # vision fallback is best-effort
        log.warning("Vision transcription failed: %s", exc)
        return ""
