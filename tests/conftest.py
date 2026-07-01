"""Shared test fixtures and helpers.

Tests avoid downloading the real embedding model (and calling any network API):
* :class:`DeterministicEmbedder` produces stable, normalized vectors from text,
  so ingestion + retrieval can be exercised offline.
* The ``require_db`` fixture skips integration tests when Postgres is unreachable.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pymupdf as fitz
import pytest

from src.config import Settings, get_settings


# ── Deterministic, offline embedder ──────────────────────────────────────────
class DeterministicEmbedder:
    """Stable, L2-normalized pseudo-embeddings derived from the text itself.

    Identical text → identical vector, so a query equal to a stored passage
    retrieves that passage with cosine similarity ~1.0.
    """

    def __init__(self, dim: int) -> None:
        self.dimension = dim

    def _vec(self, text: str) -> np.ndarray:
        seed = int.from_bytes(text.encode("utf-8"), "little", signed=False) % (2**32)
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dimension).astype(np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    def encode_query(self, text: str) -> np.ndarray:
        return self._vec(text)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        return np.stack([self._vec(t) for t in texts])


@pytest.fixture
def det_embedder() -> DeterministicEmbedder:
    return DeterministicEmbedder(get_settings().embedding_dim)


# ── Settings helper (no .env dependence) ─────────────────────────────────────
def make_settings(**overrides) -> Settings:
    base = dict(
        embedding_model="test-model",
        embedding_dim=8,
        embedding_query_prefix="query:",
        embedding_passage_prefix="passage:",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


# ── PDF builders ─────────────────────────────────────────────────────────────
def make_pdf(path: Path, pages_text: list[str]) -> Path:
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    return make_pdf(
        tmp_path / "text.pdf",
        ["Substation OHS rules and switching procedures. " * 20] * 2,
    )


@pytest.fixture
def blank_pdf(tmp_path: Path) -> Path:
    # Blank (no text layer) pages simulate a scanned/image document.
    return make_pdf(tmp_path / "scanned.pdf", ["", "", ""])


# ── Database fixture (integration) ───────────────────────────────────────────
@pytest.fixture(scope="session")
def require_db() -> Settings:
    settings = get_settings()
    import psycopg

    try:
        with psycopg.connect(settings.database_url, connect_timeout=3):
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres+pgvector not available: {exc}")

    from src.db import init_schema

    init_schema(settings)
    return settings


def unique_hash() -> str:
    return uuid.uuid4().hex
