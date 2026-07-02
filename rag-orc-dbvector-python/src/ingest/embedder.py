"""Sentence-transformers wrapper — the SINGLE embedding entry point.

Ingestion and query MUST embed text identically (same model, same normalization,
same instruction prefixes), so both import :func:`get_embedder` from here.

Asymmetric models such as ``intfloat/multilingual-e5-base`` require different
instruction prefixes for the stored passages (``passage:``) and the search
query (``query:``). Those prefixes are configurable; set them empty for a
symmetric model like ``paraphrase-multilingual-MiniLM-L12-v2``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from ..config import Settings, get_settings
from ..errors import EmbeddingDimensionMismatch
from ..logging_config import get_logger

if TYPE_CHECKING:  # avoid importing torch/sentence-transformers at module load
    from sentence_transformers import SentenceTransformer

log = get_logger(__name__)


class Embedder:
    """Lazy-loading wrapper around a SentenceTransformer model.

    Interface (also satisfied by test stubs):
      * ``dimension`` -> int
      * ``encode_query(text)`` -> 1-D ``np.ndarray`` of shape (dim,)
      * ``encode_passages(texts)`` -> 2-D ``np.ndarray`` of shape (n, dim)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._model: "SentenceTransformer | None" = None

    # ── model loading ─────────────────────────────────────────────────────────
    def _ensure_model(self) -> "SentenceTransformer":
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            log.info("Loading embedding model '%s'…", self.settings.embedding_model)
            model = SentenceTransformer(self.settings.embedding_model)
            # sentence-transformers renamed this method in 5.x; support both.
            get_dim = getattr(model, "get_embedding_dimension", None) or (
                model.get_sentence_embedding_dimension
            )
            actual = get_dim()
            if actual != self.settings.embedding_dim:
                raise EmbeddingDimensionMismatch(
                    f"Model '{self.settings.embedding_model}' produces {actual}-dim "
                    f"vectors but EMBEDDING_DIM={self.settings.embedding_dim}. "
                    f"Set EMBEDDING_DIM={actual} (and re-create the chunks table)."
                )
            self._model = model
            log.info("Embedding model ready (dim=%d).", actual)
        return self._model

    @property
    def dimension(self) -> int:
        return self.settings.embedding_dim

    # ── prefixing ─────────────────────────────────────────────────────────────
    def _with_prefix(self, prefix: str, text: str) -> str:
        prefix = prefix.strip()
        return f"{prefix} {text}" if prefix else text

    # ── encoding ──────────────────────────────────────────────────────────────
    def encode_passages(self, texts: list[str]) -> np.ndarray:
        """Embed document passages for storage. Returns shape (len(texts), dim)."""
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        model = self._ensure_model()
        prepared = [self._with_prefix(self.settings.embedding_passage_prefix, t) for t in texts]
        vecs = model.encode(
            prepared,
            normalize_embeddings=self.settings.embedding_normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        """Embed a single search query. Returns shape (dim,)."""
        model = self._ensure_model()
        prepared = self._with_prefix(self.settings.embedding_query_prefix, text)
        vec = model.encode(
            prepared,
            normalize_embeddings=self.settings.embedding_normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vec, dtype=np.float32)


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Return the process-wide embedder singleton (model loaded lazily on first use)."""
    return Embedder()
