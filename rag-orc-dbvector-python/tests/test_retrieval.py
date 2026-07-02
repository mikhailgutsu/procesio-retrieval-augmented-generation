"""Round-trip retrieval and metadata resolution on a small seeded dataset.

Marked ``integration`` — requires a running Postgres+pgvector (``make db-up``).
Uses the offline DeterministicEmbedder so no model download / network is needed.
"""

from __future__ import annotations

import pytest

from tests.conftest import unique_hash

pytestmark = pytest.mark.integration


def _seed(settings, det_embedder, pages, **doc_kwargs):
    from src.db import connection, insert_chunks, insert_document

    embs = det_embedder.encode_passages(pages)
    with connection(settings) as conn:
        doc_id = insert_document(
            conn,
            filename=doc_kwargs.get("filename", "test_manual.pdf"),
            source=doc_kwargs.get("source", "test"),
            num_pages=len(pages),
            content_hash=unique_hash(),
            text_pdf_path=doc_kwargs.get("text_pdf_path"),
        )
        insert_chunks(conn, doc_id, [(i + 1, pages[i], embs[i]) for i in range(len(pages))])
        conn.commit()
    return doc_id


def _cleanup(settings, doc_id):
    from src.db import connection, delete_document

    with connection(settings) as conn:
        delete_document(conn, doc_id)
        conn.commit()


def test_round_trip_retrieval(require_db, det_embedder):
    from src.query.retriever import retrieve

    settings = require_db
    pages = [
        "PPE required: helmet and insulating gloves before any switching.",
        "Switching order procedure and interlock verification steps.",
        "Grounding and voltage checks required before re-energizing.",
    ]
    doc_id = _seed(settings, det_embedder, pages)
    try:
        hits = retrieve(pages[0], k=3, settings=settings, embedder=det_embedder)
        assert hits, "expected at least one hit"
        top = hits[0]
        # The identical page must come back first (cosine ~1.0).
        assert top.content == pages[0]
        assert top.score > 0.99
        # Metadata resolution.
        assert top.document_id == doc_id
        assert top.filename == "test_manual.pdf"
        assert top.page_number == 1
    finally:
        _cleanup(settings, doc_id)


def test_metadata_resolution_fields(require_db, det_embedder):
    from src.query.retriever import retrieve

    settings = require_db
    pages = ["alpha unique content", "beta unique content"]
    doc_id = _seed(
        settings,
        det_embedder,
        pages,
        filename="meta.pdf",
        source="/data/raw/meta.pdf",
        text_pdf_path="/data/processed/meta.ocr.pdf",
    )
    try:
        hits = retrieve(pages[1], k=2, settings=settings, embedder=det_embedder)
        top = hits[0]
        assert top.page_number == 2
        assert top.filename == "meta.pdf"
        assert top.source == "/data/raw/meta.pdf"
        assert top.text_pdf_path == "/data/processed/meta.ocr.pdf"
    finally:
        _cleanup(settings, doc_id)


def test_top_k_limit(require_db, det_embedder):
    from src.query.retriever import retrieve

    settings = require_db
    pages = [f"unique page number {i}" for i in range(6)]
    doc_id = _seed(settings, det_embedder, pages, filename="k.pdf")
    try:
        assert len(retrieve("unique page number 0", k=2, settings=settings, embedder=det_embedder)) <= 2
    finally:
        _cleanup(settings, doc_id)
