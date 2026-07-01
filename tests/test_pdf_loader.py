"""Scanned-vs-text detection and per-page extraction."""

from __future__ import annotations

from src.ingest.pdf_loader import detect_scanned, extract_pages_text, is_scanned_pdf
from tests.conftest import make_settings


def test_detect_scanned_pure_logic():
    text_pages = ["real content " * 20, "more content " * 20]
    scan_pages = ["", "", "x"]

    assert detect_scanned(text_pages, char_threshold=100, page_ratio=0.5).is_scanned is False
    d = detect_scanned(scan_pages, char_threshold=100, page_ratio=0.5)
    assert d.is_scanned is True
    assert d.empty_pages == 3  # "x" is below the 100-char threshold too
    assert d.num_pages == 3


def test_extract_pages_text_counts_pages(text_pdf):
    pages = extract_pages_text(text_pdf)
    assert len(pages) == 2
    assert "Substation" in pages[0]


def test_is_scanned_pdf_born_digital(text_pdf):
    settings = make_settings(scanned_char_threshold=100, scanned_page_ratio=0.5)
    assert is_scanned_pdf(text_pdf, settings) is False


def test_is_scanned_pdf_blank_pages(blank_pdf):
    settings = make_settings(scanned_char_threshold=100, scanned_page_ratio=0.5)
    assert is_scanned_pdf(blank_pdf, settings) is True
