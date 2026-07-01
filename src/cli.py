"""Command-line interface for the RAG assistant.

    python -m src.cli init-db
    python -m src.cli ingest [--dir data/raw | --path file.pdf]
    python -m src.cli ask "your question" [-k 5] [--retrieve-only] [--no-highlight] [--json]
    python -m src.cli stats
    python -m src.cli reset-db [--yes]
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import get_settings
from .errors import ConfigError, RagError
from .logging_config import configure_logging, get_logger

log = get_logger(__name__)


def _cmd_init_db(args: argparse.Namespace) -> int:
    from .db import init_schema

    init_schema()
    print("Schema initialized.")
    return 0


def _cmd_reset_db(args: argparse.Namespace) -> int:
    from .db import init_schema, reset_schema

    if not args.yes:
        reply = input("This DROPS the documents and chunks tables. Continue? [y/N] ")
        if reply.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1
    reset_schema()
    init_schema()
    print("Schema reset.")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from .ingest.pipeline import ingest_directory, ingest_file
    from .db import init_schema

    init_schema()
    if args.path:
        results = [ingest_file(args.path)]
    else:
        results = ingest_directory(args.dir)

    if not results:
        print("No ingestable files (PDF/image/pptx/xlsx) found.")
        return 0
    print(f"\n{'FILE':40} {'DOC ID':>7} {'PAGES':>6} {'CHUNKS':>7}  STATUS")
    for r in results:
        if r.errors:
            status = f"ERROR: {r.errors[0][:40]}"
        elif r.skipped:
            status = "skipped"
        else:
            status = (r.kind or "ok") + (" (ocr)" if r.was_ocred else "")
        print(
            f"{r.filename[:40]:40} {str(r.document_id or '-'):>7} "
            f"{r.num_pages:>6} {r.num_chunks:>7}  {status}"
        )
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    settings = get_settings()

    if args.retrieve_only:
        from .query.retriever import retrieve

        hits = retrieve(args.question, k=args.k)
        if args.json:
            print(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2))
            return 0
        if not hits:
            print("No results — is anything ingested?")
            return 0
        print(f"\nTop {len(hits)} pages for: {args.question}\n")
        for h in hits:
            print(f"  [{h.score:.3f}] {h.filename} p.{h.page_number}")
            print(f"        {h.content.strip()[:160]}…\n")
        return 0

    from .query.pipeline import answer_question

    try:
        result = answer_question(
            args.question, k=args.k, do_highlight=not args.no_highlight
        )
    except ConfigError as exc:
        print(f"\nConfiguration error: {exc}", file=sys.stderr)
        print("Tip: set ANTHROPIC_API_KEY in .env, or use --retrieve-only.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"\nQ: {result.question}")
    print(f"\nA: {result.answer}\n")
    if result.citations:
        print("Sources:")
        for c in result.citations:
            print(f"  - {c.filename} p.{c.page_number}  (score {c.score:.3f})")
    if result.highlights:
        print("\nHighlights (verbatim spans):")
        for h in result.highlights:
            loc = f"chars {h.char_start}-{h.char_end}" if h.matched_in_chunk else "offset n/a"
            pdf = f"  → {h.page_image}" if h.page_image else ""
            print(f"  - {h.filename} p.{h.page_number} [{loc}]{pdf}")
            print(f"      “{h.text.strip()[:160]}”")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    from .db import connection, counts

    with connection() as conn:
        c = counts(conn)
    print(f"documents: {c['documents']}")
    print(f"chunks:    {c['chunks']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rag", description="RAG technical documentation assistant")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the schema (idempotent).")

    reset = sub.add_parser("reset-db", help="Drop and re-create the schema (destructive).")
    reset.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    ing = sub.add_parser("ingest", help="Ingest PDFs into the store.")
    g = ing.add_mutually_exclusive_group()
    g.add_argument("--path", help="Ingest a single PDF file.")
    g.add_argument("--dir", help="Ingest all PDFs in a directory (default: DATA_RAW_DIR).")

    ask = sub.add_parser("ask", help="Ask a question.")
    ask.add_argument("question", help="The question, in quotes.")
    ask.add_argument("-k", type=int, default=None, help="Top-k chunks to retrieve.")
    ask.add_argument("--retrieve-only", action="store_true", help="Skip the LLM; show pages only.")
    ask.add_argument("--no-highlight", action="store_true", help="Skip PDF highlighting.")
    ask.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    sub.add_parser("stats", help="Show document/chunk counts.")
    return p


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "init-db": _cmd_init_db,
        "reset-db": _cmd_reset_db,
        "ingest": _cmd_ingest,
        "ask": _cmd_ask,
        "stats": _cmd_stats,
    }
    try:
        return handlers[args.command](args)
    except RagError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
