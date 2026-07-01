"""LLM extraction logic (with a fake Claude client — no network).

Verifies structured parsing, that spans stay verbatim, and that spans citing
pages we did not provide are dropped (defense against hallucinated citations).
"""

from __future__ import annotations

import json

from src.query.extractor import extract_answer
from src.query.retriever import RetrievedChunk
from tests.conftest import make_settings


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._payload)


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self.messages = _FakeMessages(payload)


def _chunk(doc_id: int, page: int, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        document_id=doc_id,
        filename="manual.pdf",
        source=None,
        text_pdf_path=None,
        page_number=page,
        content=content,
        score=0.9,
    )


def test_extractor_returns_verbatim_spans():
    chunks = [
        _chunk(1, 1, "PPE required: helmet and insulating gloves."),
        _chunk(1, 2, "Switching order steps follow."),
    ]
    payload = json.dumps(
        {
            "answerable": True,
            "answer": "Helmet and insulating gloves are required.",
            "spans": [{"document_id": 1, "page_number": 1, "text": "helmet and insulating gloves"}],
        }
    )
    result = extract_answer(
        "What PPE is required?",
        chunks,
        settings=make_settings(anthropic_api_key="test"),
        client=_FakeClient(payload),
    )
    assert result.answerable is True
    assert len(result.spans) == 1
    span = result.spans[0]
    assert span.text == "helmet and insulating gloves"
    assert span.text in chunks[0].content  # verbatim: exact substring of the source page


def test_extractor_drops_spans_from_nonprovided_pages():
    chunks = [_chunk(1, 1, "page one content")]
    payload = json.dumps(
        {
            "answerable": True,
            "answer": "…",
            "spans": [{"document_id": 9, "page_number": 9, "text": "hallucinated"}],
        }
    )
    result = extract_answer(
        "q", chunks, settings=make_settings(anthropic_api_key="test"), client=_FakeClient(payload)
    )
    assert result.spans == []


def test_extractor_short_circuits_without_chunks():
    result = extract_answer("q", [], settings=make_settings(anthropic_api_key="test"))
    assert result.answerable is False
    assert result.spans == []
