"""RAG-based technical documentation assistant.

Two pipelines share one PostgreSQL/pgvector database:

* ``src.ingest``  — PDF → (OCR) → per-page chunks → embeddings → store.
* ``src.query``   — question → embed → vector search → LLM extract → highlight.
"""

__version__ = "0.1.0"
