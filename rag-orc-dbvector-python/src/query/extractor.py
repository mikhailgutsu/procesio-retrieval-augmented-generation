"""LLM answer extraction (Anthropic Claude).

Given the question and the retrieved page texts, Claude returns the **verbatim**
answering spans (exact substrings of the source pages) together with each span's
``document_id`` and ``page_number``, plus a short grounded answer. Output is a
strict JSON structure so the spans can be located for highlighting. The model is
instructed to ground its answer only in the provided pages and to say when they
do not contain the answer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..errors import ExtractionError
from ..logging_config import get_logger

if TYPE_CHECKING:
    from .retriever import RetrievedChunk

log = get_logger(__name__)


# ── Structured output schema ─────────────────────────────────────────────────
class AnswerSpan(BaseModel):
    document_id: int
    page_number: int
    text: str = Field(description="Verbatim substring copied exactly from the page text")


class ExtractionResult(BaseModel):
    answerable: bool
    answer: str
    spans: list[AnswerSpan] = Field(default_factory=list)


# JSON schema for structured outputs (additionalProperties:false + required on all).
_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "answer": {"type": "string"},
        "spans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "integer"},
                    "page_number": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["document_id", "page_number", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answerable", "answer", "spans"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a technical documentation assistant for electrical substation "
    "operations. Answer strictly and only from the provided document pages. "
    "Copy answering spans VERBATIM — each span's text must be an exact substring "
    "of the page it comes from (same characters, accents and punctuation), so it "
    "can be located and highlighted in the source. Never invent content or cite a "
    "page you were not given. If the pages do not contain the answer, set "
    "answerable=false, give a short answer saying so, and return an empty spans "
    "list. Answer in the language of the question."
)


def _build_user_prompt(question: str, chunks: list["RetrievedChunk"]) -> str:
    blocks = []
    for c in chunks:
        blocks.append(
            f"[document_id={c.document_id} | file={c.filename} | page={c.page_number}]\n"
            f"{c.content.strip()}"
        )
    context = "\n\n---\n\n".join(blocks)
    return (
        f"QUESTION:\n{question}\n\n"
        f"SOURCE PAGES:\n\n{context}\n\n"
        "Return the answer and the verbatim answering spans as JSON."
    )


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Be tolerant of a stray prose wrapper: grab the outermost JSON object.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def extract_answer(
    question: str,
    chunks: list["RetrievedChunk"],
    settings: Settings | None = None,
    client: Any | None = None,
) -> ExtractionResult:
    """Extract verbatim answering spans grounded in ``chunks`` (provider-agnostic)."""
    from ..llm import complete_json

    settings = settings or get_settings()
    if not chunks:
        return ExtractionResult(
            answerable=False, answer="No relevant pages were retrieved.", spans=[]
        )

    user = _build_user_prompt(question, chunks)
    log.info(
        "Extracting answer with provider=%s over %d page(s)…", settings.llm_provider, len(chunks)
    )
    text = complete_json(_SYSTEM, user, settings=settings, json_schema=_JSON_SCHEMA, client=client)

    try:
        result = ExtractionResult.model_validate(_extract_json(text))
    except Exception as exc:
        raise ExtractionError(f"Could not parse structured answer: {exc}") from exc

    # Keep only spans that cite a page we actually provided.
    allowed = {(c.document_id, c.page_number) for c in chunks}
    kept = [s for s in result.spans if (s.document_id, s.page_number) in allowed]
    if len(kept) != len(result.spans):
        log.warning("Dropped %d span(s) citing non-provided pages.", len(result.spans) - len(kept))
    result.spans = kept
    return result
