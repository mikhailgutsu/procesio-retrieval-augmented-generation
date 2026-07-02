"""Chunk creation: the v1 rule (1 page = 1 chunk) and the pluggable window strategy."""

from __future__ import annotations

import pytest

from src.ingest.chunker import Chunk, FixedWindowChunker, PageChunker, get_chunker
from tests.conftest import make_settings


def test_page_chunker_one_chunk_per_nonempty_page():
    pages = ["first page text", "   ", "third page text"]
    chunks = PageChunker().chunk(pages)
    assert [c.page_number for c in chunks] == [1, 3]  # empty page 2 skipped, numbers stay 1-based
    assert chunks[0].content == "first page text"
    assert chunks[1].content == "third page text"
    assert all(isinstance(c, Chunk) for c in chunks)


def test_page_chunker_can_keep_empty_pages():
    chunks = PageChunker(skip_empty=False).chunk(["a", "", "c"])
    assert [c.page_number for c in chunks] == [1, 2, 3]


def test_fixed_window_chunker_windows_within_page():
    # 20 chars, size 10, overlap 3 → step 7 → windows at 0, 7, 14 → 3 chunks.
    chunks = FixedWindowChunker(size=10, overlap=3).chunk(["abcdefghijklmnopqrst"])
    assert len(chunks) == 3
    assert chunks[0].content == "abcdefghij"
    assert all(c.page_number == 1 for c in chunks)


def test_fixed_window_validates_overlap():
    with pytest.raises(ValueError):
        FixedWindowChunker(size=10, overlap=10)


def test_get_chunker_selects_strategy_from_config():
    assert isinstance(get_chunker(make_settings(chunk_strategy="page")), PageChunker)
    assert isinstance(get_chunker(make_settings(chunk_strategy="window")), FixedWindowChunker)
