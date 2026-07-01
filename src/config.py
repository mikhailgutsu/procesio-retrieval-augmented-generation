"""Environment-driven configuration.

Everything that varies between deployments — the embedding model and its
dimension, the database URL, top-k, and the LLM settings — is read from the
environment (optionally via a `.env` file). Changing the embedding model must
not require code edits beyond this config (and re-creating the `chunks` table
if the vector dimension changes).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = "postgresql://rag:rag@localhost:5432/rag"

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dim: int = 768
    embedding_query_prefix: str = "query:"
    embedding_passage_prefix: str = "passage:"
    embedding_normalize: bool = True

    # ── Retrieval ─────────────────────────────────────────────────────────────
    top_k: int = 5

    # ── LLM (answer extraction) ───────────────────────────────────────────────
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    llm_max_tokens: int = 4096
    llm_thinking: bool = False

    # ── Ingestion ─────────────────────────────────────────────────────────────
    data_raw_dir: str = "data/raw"
    data_processed_dir: str = "data/processed"
    data_highlights_dir: str = "data/highlights"
    scanned_char_threshold: int = 100
    scanned_page_ratio: float = 0.5
    ocr_languages: str = "ron+eng"
    ocr_vision_fallback: bool = False
    chunk_strategy: str = Field(default="page", pattern="^(page|window)$")
    chunk_window_size: int = 1200
    chunk_window_overlap: int = 150
    ingest_on_duplicate: str = Field(default="skip", pattern="^(skip|replace)$")

    highlight_pdf: bool = True

    log_level: str = "INFO"

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def raw_dir(self) -> Path:
        return Path(self.data_raw_dir)

    @property
    def processed_dir(self) -> Path:
        return Path(self.data_processed_dir)

    @property
    def highlights_dir(self) -> Path:
        return Path(self.data_highlights_dir)

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.processed_dir, self.highlights_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
