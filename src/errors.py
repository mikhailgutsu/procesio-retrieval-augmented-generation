"""Typed exceptions so each pipeline stage can fail clearly."""

from __future__ import annotations


class RagError(Exception):
    """Base class for all application errors."""


class ConfigError(RagError):
    """Missing or invalid configuration (e.g. no API key when one is required)."""


class SchemaDimensionMismatch(RagError):
    """The existing `chunks.embedding` column dimension != configured EMBEDDING_DIM."""


class EmbeddingDimensionMismatch(RagError):
    """The loaded embedding model produces vectors of the wrong dimension."""


class OcrError(RagError):
    """OCR (ocrmypdf/Tesseract) failed to produce a text-layer PDF."""


class EmptyRetrievalError(RagError):
    """Vector search returned no candidate chunks (empty or non-ingested store)."""


class ExtractionError(RagError):
    """The LLM answer-extraction step failed or returned unusable output."""
