"""Pluggable chunking. v1 rule: 1 chunk = the full text of 1 page.

The pipeline depends only on the :class:`BaseChunker` interface, so a finer
strategy (fixed windows with overlap) can replace the page strategy purely via
config (``CHUNK_STRATEGY``) without touching the rest of the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import Settings, get_settings


@dataclass
class Chunk:
    page_number: int  # 1-based source page the text came from
    content: str


class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, pages_text: list[str]) -> list[Chunk]:
        """Turn a list of per-page texts (index 0 == page 1) into chunks."""


class PageChunker(BaseChunker):
    """v1: one chunk per page. Empty pages are skipped but page numbers stay 1-based."""

    def __init__(self, skip_empty: bool = True) -> None:
        self.skip_empty = skip_empty

    def chunk(self, pages_text: list[str]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for idx, text in enumerate(pages_text):
            page_number = idx + 1
            if self.skip_empty and not text.strip():
                continue
            chunks.append(Chunk(page_number=page_number, content=text))
        return chunks


class FixedWindowChunker(BaseChunker):
    """Fixed-size character windows with overlap, kept within a single page so the
    page_number metadata stays exact."""

    def __init__(self, size: int, overlap: int, skip_empty: bool = True) -> None:
        if size <= 0:
            raise ValueError("window size must be > 0")
        if overlap < 0 or overlap >= size:
            raise ValueError("overlap must satisfy 0 <= overlap < size")
        self.size = size
        self.overlap = overlap
        self.skip_empty = skip_empty

    def chunk(self, pages_text: list[str]) -> list[Chunk]:
        chunks: list[Chunk] = []
        step = self.size - self.overlap
        for idx, text in enumerate(pages_text):
            page_number = idx + 1
            if self.skip_empty and not text.strip():
                continue
            start = 0
            while start < len(text):
                window = text[start : start + self.size]
                if window.strip():
                    chunks.append(Chunk(page_number=page_number, content=window))
                start += step
        return chunks


def get_chunker(settings: Settings | None = None) -> BaseChunker:
    settings = settings or get_settings()
    if settings.chunk_strategy == "window":
        return FixedWindowChunker(settings.chunk_window_size, settings.chunk_window_overlap)
    return PageChunker()
