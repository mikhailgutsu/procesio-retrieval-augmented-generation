"""PostgreSQL + pgvector access layer.

Owns the connection pool, idempotent schema creation, and the low-level SQL used
by both pipelines (insert during ingestion, cosine search during retrieval).

The `chunks.embedding` column dimension is written from ``EMBEDDING_DIM`` at
schema-init time. If you change the embedding model to one with a different
dimension you must re-create the table (``make db-reset`` / :func:`reset_schema`).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings, get_settings
from .errors import SchemaDimensionMismatch
from .logging_config import get_logger

log = get_logger(__name__)

_POOL: ConnectionPool | None = None


def _register_vector(conn: psycopg.Connection) -> None:
    """Register the pgvector adapter, creating the extension first if needed."""
    from pgvector.psycopg import register_vector

    try:
        register_vector(conn)
    except psycopg.errors.ProgrammingError:
        # The `vector` type does not exist yet — create the extension and retry.
        conn.rollback()
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        register_vector(conn)


def get_pool(settings: Settings | None = None) -> ConnectionPool:
    global _POOL
    if _POOL is None:
        settings = settings or get_settings()
        _POOL = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=8,
            kwargs={"autocommit": False},
            configure=_register_vector,
            open=True,
        )
    return _POOL


@contextmanager
def connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    """Borrow a connection from the pool (vector adapter already registered)."""
    pool = get_pool(settings)
    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.close()
        _POOL = None


def _schema_ddl(dim: int) -> str:
    return f"""
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS documents (
        id            SERIAL PRIMARY KEY,
        filename      TEXT NOT NULL,
        source        TEXT,
        num_pages     INTEGER,
        content_hash  TEXT UNIQUE,          -- sha256 of the raw file, for dedupe
        text_pdf_path TEXT,                 -- text-bearing PDF used for extraction
        created_at    TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS chunks (
        id           SERIAL PRIMARY KEY,
        document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        page_number  INTEGER NOT NULL,
        content      TEXT NOT NULL,
        embedding    VECTOR({dim}) NOT NULL,
        created_at   TIMESTAMPTZ DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS chunks_embedding_idx
        ON chunks USING hnsw (embedding vector_cosine_ops);

    CREATE INDEX IF NOT EXISTS chunks_document_id_idx
        ON chunks (document_id);

    -- Full-text index for hybrid (keyword) search. 'simple' config is
    -- language-agnostic, which suits mixed Romanian/English + brand names.
    CREATE INDEX IF NOT EXISTS chunks_content_fts_idx
        ON chunks USING gin (to_tsvector('simple', content));
    """


def init_schema(settings: Settings | None = None) -> None:
    """Create the extension, tables and indexes if absent (idempotent).

    Uses a direct connection (not the pool) so it works before the pgvector
    adapter can be registered. Verifies the existing vector dimension matches
    the configured one and fails clearly on mismatch.
    """
    settings = settings or get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(_schema_ddl(settings.embedding_dim))
        _verify_dimension(conn, settings.embedding_dim)
    log.info(
        "Schema ready (embedding dim=%d, model=%s).",
        settings.embedding_dim,
        settings.embedding_model,
    )


def _verify_dimension(conn: psycopg.Connection, expected: int) -> None:
    row = conn.execute(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        WHERE a.attrelid = 'chunks'::regclass AND a.attname = 'embedding'
        """
    ).fetchone()
    if not row:
        return
    actual = row[0]  # pgvector stores the dimension directly in atttypmod (-1 = unspecified)
    if actual not in (-1, expected):
        raise SchemaDimensionMismatch(
            f"chunks.embedding is VECTOR({actual}) but EMBEDDING_DIM={expected}. "
            f"Change EMBEDDING_DIM back to {actual}, or re-create the table "
            f"(make db-reset) after changing the embedding model."
        )


def reset_schema(settings: Settings | None = None) -> None:
    """Drop the RAG tables. Destructive — used by `make db-reset` and tests."""
    settings = settings or get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS chunks CASCADE")
        conn.execute("DROP TABLE IF EXISTS documents CASCADE")
    log.warning("Dropped tables `chunks` and `documents`.")


def find_document_by_hash(conn: psycopg.Connection, content_hash: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT * FROM documents WHERE content_hash = %s", (content_hash,)
        ).fetchone()


def get_document(conn: psycopg.Connection, document_id: int) -> dict[str, Any] | None:
    """Return the documents row for ``document_id`` (or None), used for downloads."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT * FROM documents WHERE id = %s", (document_id,)
        ).fetchone()


def get_document_chunks(conn: psycopg.Connection, document_id: int) -> list[dict[str, Any]]:
    """Return the stored (page_number, content) chunks for a document, in order.

    This is the text the RAG pipeline actually indexed (OCR / vision / native
    extraction) — used to preview what the system "sees" for a document.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT page_number, content
            FROM chunks
            WHERE document_id = %s
            ORDER BY page_number, id
            """,
            (document_id,),
        ).fetchall()


def delete_document(conn: psycopg.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))


def insert_document(
    conn: psycopg.Connection,
    *,
    filename: str,
    source: str | None,
    num_pages: int,
    content_hash: str,
    text_pdf_path: str | None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO documents (filename, source, num_pages, content_hash, text_pdf_path)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (filename, source, num_pages, content_hash, text_pdf_path),
    ).fetchone()
    assert row is not None
    return int(row[0])


def insert_chunks(
    conn: psycopg.Connection,
    document_id: int,
    rows: Sequence[tuple[int, str, Any]],
) -> int:
    """Bulk-insert (page_number, content, embedding) rows for one document.

    ``embedding`` is a numpy array or list; the pgvector adapter handles it.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO chunks (document_id, page_number, content, embedding)
            VALUES (%s, %s, %s, %s)
            """,
            [(document_id, page, content, emb) for (page, content, emb) in rows],
        )
    return len(rows)


def search_chunks(
    conn: psycopg.Connection,
    query_embedding: Any,
    k: int,
) -> list[dict[str, Any]]:
    """Return the top-k chunks by cosine similarity, with document metadata.

    ``score`` is cosine similarity in [-1, 1] (1 = identical direction); the
    `<=>` operator computes cosine *distance*, so similarity = 1 - distance.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            SELECT
                c.id            AS chunk_id,
                c.document_id   AS document_id,
                d.filename      AS filename,
                d.source        AS source,
                d.text_pdf_path AS text_pdf_path,
                c.page_number   AS page_number,
                c.content       AS content,
                1 - (c.embedding <=> %s) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            ORDER BY c.embedding <=> %s
            LIMIT %s
            """,
            (query_embedding, query_embedding, k),
        ).fetchall()
    for r in rows:
        r["keyword_hit"] = False
    return rows


def search_chunks_hybrid(
    conn: psycopg.Connection,
    query_embedding: Any,
    query_text: str,
    k: int,
    candidate_k: int = 40,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: fuse dense vector search with full-text keyword search.

    Each ranker contributes its top ``candidate_k`` chunks; results are merged with
    Reciprocal Rank Fusion (``1/(rrf_k+rank)`` summed across rankers) and the top
    ``k`` are returned. Each row carries the cosine ``score`` (for thresholding /
    display) and ``keyword_hit`` (True when the full-text ranker matched it), so
    exact rare-term matches can be kept regardless of their vector score.

    Falls back to pure vector search when the query has no usable keyword terms.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            WITH vector_search AS (
                SELECT c.id,
                       row_number() OVER (ORDER BY c.embedding <=> %(emb)s) AS rank
                FROM chunks c
                ORDER BY c.embedding <=> %(emb)s
                LIMIT %(cand)s
            ),
            keyword_search AS (
                SELECT c.id,
                       row_number() OVER (
                           ORDER BY ts_rank_cd(to_tsvector('simple', c.content), q) DESC
                       ) AS rank
                FROM chunks c, websearch_to_tsquery('simple', %(q)s) AS q
                WHERE to_tsvector('simple', c.content) @@ q
                LIMIT %(cand)s
            ),
            fused AS (
                SELECT
                    COALESCE(v.id, k.id) AS id,
                    COALESCE(1.0 / (%(rrf)s + v.rank), 0.0)
                        + COALESCE(1.0 / (%(rrf)s + k.rank), 0.0) AS rrf_score,
                    (k.id IS NOT NULL) AS keyword_hit
                FROM vector_search v
                FULL OUTER JOIN keyword_search k ON v.id = k.id
            )
            SELECT
                c.id            AS chunk_id,
                c.document_id   AS document_id,
                d.filename      AS filename,
                d.source        AS source,
                d.text_pdf_path AS text_pdf_path,
                c.page_number   AS page_number,
                c.content       AS content,
                1 - (c.embedding <=> %(emb)s) AS score,
                f.keyword_hit   AS keyword_hit,
                f.rrf_score     AS rrf_score
            FROM fused f
            JOIN chunks c    ON c.id = f.id
            JOIN documents d ON d.id = c.document_id
            ORDER BY f.rrf_score DESC
            LIMIT %(k)s
            """,
            {
                "emb": query_embedding,
                "q": query_text,
                "cand": candidate_k,
                "rrf": rrf_k,
                "k": k,
            },
        ).fetchall()
    return rows


def counts(conn: psycopg.Connection) -> dict[str, int]:
    docs = conn.execute("SELECT count(*) FROM documents").fetchone()
    chks = conn.execute("SELECT count(*) FROM chunks").fetchone()
    return {"documents": int(docs[0]), "chunks": int(chks[0])}
