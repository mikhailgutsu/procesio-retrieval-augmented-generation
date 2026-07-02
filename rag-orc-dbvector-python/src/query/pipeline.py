"""Query orchestration — runs steps 1–6 to answer a question.

  1. Accept the question (plain text).
  2. Embed the question (same embedder as ingestion).
  3. Vector search (pgvector, top-k by cosine distance).
  4. Resolve metadata (document + page + score per hit).
  5. Extract verbatim answering spans with the LLM (grounded, structured).
  6. Highlight the spans (UI payload + optional PDF annotation).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..config import Settings, get_settings
from ..ingest.embedder import Embedder, get_embedder
from ..logging_config import get_logger
from .extractor import extract_answer
from .highlighter import Highlight, build_highlights
from .retriever import RetrievedChunk, retrieve

log = get_logger(__name__)


@dataclass
class Citation:
    document_id: int
    filename: str
    page_number: int
    score: float


@dataclass
class AnswerResult:
    question: str
    answerable: bool
    answer: str
    citations: list[Citation] = field(default_factory=list)
    highlights: list[Highlight] = field(default_factory=list)
    retrieved: list[RetrievedChunk] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answerable": self.answerable,
            "answer": self.answer,
            "citations": [asdict(c) for c in self.citations],
            "highlights": [asdict(h) for h in self.highlights],
            "retrieved": [
                {
                    "document_id": r.document_id,
                    "filename": r.filename,
                    "page_number": r.page_number,
                    "score": round(r.score, 4),
                    "preview": r.content.strip()[:200],
                }
                for r in self.retrieved
            ],
        }


def answer_question(
    question: str,
    k: int | None = None,
    do_highlight: bool | None = None,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
    client=None,
) -> AnswerResult:
    """Answer ``question`` end-to-end: retrieve → extract → highlight."""
    settings = settings or get_settings()
    embedder = embedder or get_embedder()

    # 2–4. Embed, search, resolve metadata.
    chunks = retrieve(question, k=k, settings=settings, embedder=embedder)
    if not chunks:
        log.warning("Empty retrieval for question %r.", question[:60])
        return AnswerResult(
            question=question,
            answerable=False,
            answer=(
                "No relevant pages were found. Ingest documents into data/raw/ "
                "first, or rephrase the question."
            ),
        )

    citations = [
        Citation(c.document_id, c.filename, c.page_number, round(c.score, 4)) for c in chunks
    ]

    # 5. Extract verbatim answering spans with the LLM.
    extraction = extract_answer(question, chunks, settings=settings, client=client)

    # 6. Highlight (UI payload + optional PDF annotation).
    highlights: list[Highlight] = []
    if extraction.spans and (do_highlight if do_highlight is not None else True):
        highlights = build_highlights(extraction.spans, chunks, settings=settings)

    return AnswerResult(
        question=question,
        answerable=extraction.answerable,
        answer=extraction.answer,
        citations=citations,
        highlights=highlights,
        retrieved=chunks,
    )
