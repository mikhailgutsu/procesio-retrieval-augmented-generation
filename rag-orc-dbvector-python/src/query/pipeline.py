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

    # Relevance gate: keep vector hits at/above the floor, but always keep exact
    # keyword matches (rare brand names, IDs) even when their vector score is low.
    # If nothing clears the bar, don't answer from irrelevant pages — say so.
    min_score = settings.retrieval_min_score
    if min_score > 0:
        kept = [c for c in chunks if c.keyword_hit or c.score >= min_score]
        if len(kept) != len(chunks):
            log.info(
                "Relevance gate kept %d/%d chunk(s) (min_score=%.2f, top=%.3f).",
                len(kept), len(chunks), min_score, chunks[0].score,
            )
        if not kept:
            return AnswerResult(
                question=question,
                answerable=False,
                answer=(
                    "I couldn't find sufficiently relevant information in the ingested "
                    "documents to answer this. Try rephrasing, or ingest the relevant file."
                ),
            )
        chunks = kept

    # 5. Extract verbatim answering spans with the LLM.
    extraction = extract_answer(question, chunks, settings=settings, client=client)

    # If the model couldn't ground an answer, don't present the retrieved pages as
    # sources — returning them made irrelevant files look like citations.
    if not extraction.answerable:
        return AnswerResult(
            question=question, answerable=False, answer=extraction.answer, retrieved=chunks
        )

    # Citations = the pages the model actually cited (fall back to all retrieved).
    cited = {(s.document_id, s.page_number) for s in extraction.spans}
    used = [c for c in chunks if (c.document_id, c.page_number) in cited] or chunks
    citations = [
        Citation(c.document_id, c.filename, c.page_number, round(c.score, 4)) for c in used
    ]

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
        retrieved=used,
    )
