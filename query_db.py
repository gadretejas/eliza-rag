#!/usr/bin/env python3
"""
Query enriched chunks from a contextualized_chunks.db (or test output DB).

Usage:
    python3 query_db.py --summary
    python3 query_db.py --ticker AAPL
    python3 query_db.py --ticker AAPL --section "Item 1A"
    python3 query_db.py --ticker NVDA --section "Item 7" --limit 3 --show-enriched
    python3 query_db.py --search "revenue growth"
    python3 query_db.py --db contextualization_test_output.db --summary
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB   = Path("contextualized_chunks.db")
FALLBACK_DB  = Path("contextualization_test_output.db")
PREVIEW_CHARS = 400


# ── DB helpers ─────────────────────────────────────────────────────────────────

def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"Database not found: {path}\nRun contextualize.py or contextualization_tester.py first.")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def print_separator(label: str = "") -> None:
    width = 72
    if label:
        pad = width - len(label) - 4
        print(f"── {label} {'─' * pad}")
    else:
        print("─" * width)


# ── Display modes ──────────────────────────────────────────────────────────────

def show_summary(conn: sqlite3.Connection) -> None:
    """Database-level summary: meta table + per-ticker chunk counts."""
    # Meta
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    if meta:
        print_separator("Database metadata")
        for k, v in meta.items():
            print(f"  {k:<24} {v}")
        print()

    # Overall counts
    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM chunks").fetchone()[0]
    n_files   = conn.execute("SELECT COUNT(DISTINCT source_file) FROM chunks").fetchone()[0]
    print_separator("Overview")
    print(f"  Total chunks   : {total:,}")
    print(f"  Tickers        : {n_tickers}")
    print(f"  Source files   : {n_files}")
    print()

    # Per-ticker breakdown
    print_separator("Chunks per ticker")
    rows = conn.execute("""
        SELECT ticker, COUNT(*) as n, COUNT(DISTINCT section_id) as sections,
               COUNT(DISTINCT filing_date) as filings
        FROM chunks
        GROUP BY ticker
        ORDER BY ticker
    """).fetchall()
    print(f"  {'Ticker':<8}  {'Chunks':>7}  {'Sections':>9}  {'Filings':>8}")
    print(f"  {'─'*8}  {'─'*7}  {'─'*9}  {'─'*8}")
    for r in rows:
        print(f"  {r['ticker']:<8}  {r['n']:>7,}  {r['sections']:>9}  {r['filings']:>8}")
    print()

    # Content type split
    print_separator("Content type split")
    for r in conn.execute(
        "SELECT content_type, COUNT(*) as n FROM chunks GROUP BY content_type ORDER BY n DESC"
    ):
        print(f"  {r['content_type']:<10}  {r['n']:,}")
    print()

    # Context coverage
    missing_doc = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_context IS NULL OR document_context = ''"
    ).fetchone()[0]
    missing_sec = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE section_context IS NULL OR section_context = ''"
    ).fetchone()[0]
    print_separator("Context coverage")
    print(f"  Missing document_context : {missing_doc:,}")
    print(f"  Missing section_context  : {missing_sec:,}")
    print()


def show_sections(conn: sqlite3.Connection, ticker: str) -> None:
    """List sections available for a ticker."""
    rows = conn.execute("""
        SELECT section_id, section_name, COUNT(*) as n, filing_date
        FROM chunks
        WHERE ticker = ?
        GROUP BY section_id, filing_date
        ORDER BY filing_date DESC, section_id
    """, (ticker,)).fetchall()

    if not rows:
        print(f"No chunks found for ticker '{ticker}'.")
        return

    print_separator(f"{ticker} — sections")
    print(f"  {'Section ID':<14}  {'Date':<12}  {'Chunks':>6}  Section Name")
    print(f"  {'─'*14}  {'─'*12}  {'─'*6}  {'─'*40}")
    for r in rows:
        name = r["section_name"] or ""
        print(f"  {r['section_id']:<14}  {r['filing_date']:<12}  {r['n']:>6}  {name}")
    print()


def show_chunks(
    conn: sqlite3.Connection,
    ticker: str | None,
    section: str | None,
    limit: int,
    show_enriched: bool,
    show_contexts: bool,
) -> None:
    """Show individual chunk content."""
    conditions = []
    params: list = []

    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker)
    if section:
        conditions.append("section_id = ?")
        params.append(section)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT id, ticker, filing_date, section_id, section_name,
               content_type, document_context, section_context,
               original_text, enriched_text
        FROM chunks
        {where}
        ORDER BY ticker, filing_date DESC, chunk_index
        LIMIT ?
    """
    rows = conn.execute(query, params + [limit]).fetchall()

    if not rows:
        label = f"{ticker or 'all'}" + (f" / {section}" if section else "")
        print(f"No chunks found for: {label}")
        return

    for r in rows:
        name = f" — {r['section_name']}" if r["section_name"] else ""
        print_separator(f"[{r['id']}]")
        print(f"  Ticker      : {r['ticker']}")
        print(f"  Date        : {r['filing_date']}")
        print(f"  Section     : {r['section_id']}{name}")
        print(f"  Type        : {r['content_type']}")

        if show_contexts:
            if r["document_context"]:
                print(f"\n  [DOCUMENT CONTEXT]\n  {r['document_context']}")
            if r["section_context"]:
                print(f"\n  [SECTION CONTEXT]\n  {r['section_context']}")

        text = r["enriched_text"] if show_enriched else r["original_text"]
        label = "Enriched text" if show_enriched else "Original text"
        preview = text[:PREVIEW_CHARS] + (" ..." if len(text) > PREVIEW_CHARS else "")
        print(f"\n  [{label}]\n  {preview.replace(chr(10), chr(10) + '  ')}")
        print()


def show_search(conn: sqlite3.Connection, query: str, limit: int) -> None:
    """Full-text keyword search across original_text and enriched_text."""
    pattern = f"%{query}%"
    rows = conn.execute("""
        SELECT id, ticker, filing_date, section_id, original_text
        FROM chunks
        WHERE original_text LIKE ? OR enriched_text LIKE ?
        ORDER BY ticker, filing_date DESC
        LIMIT ?
    """, (pattern, pattern, limit)).fetchall()

    if not rows:
        print(f"No results for: {query!r}")
        return

    print_separator(f"Search results for: {query!r}  ({len(rows)} shown)")
    for r in rows:
        preview = r["original_text"][:PREVIEW_CHARS].replace("\n", " ")
        print(f"  [{r['id']}]  {r['ticker']} · {r['filing_date']} · {r['section_id']}")
        print(f"    {preview} ...")
        print()


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Auto-select the test DB if the production DB is absent
    default_db = DEFAULT_DB if DEFAULT_DB.exists() else FALLBACK_DB

    parser = argparse.ArgumentParser(
        description="Query enriched chunks from a contextualized SQLite database"
    )
    parser.add_argument(
        "--db", type=Path, default=default_db,
        help=f"Path to the SQLite database (default: {default_db})",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Show database-level stats and context coverage",
    )
    parser.add_argument(
        "--ticker",
        help="Filter by ticker symbol, e.g. AAPL",
    )
    parser.add_argument(
        "--section",
        help='Filter by section ID, e.g. "Item 1A"',
    )
    parser.add_argument(
        "--search",
        help="Keyword search across chunk text",
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max chunks to display (default: 5)",
    )
    parser.add_argument(
        "--show-enriched", action="store_true",
        help="Show enriched_text instead of original_text",
    )
    parser.add_argument(
        "--show-contexts", action="store_true",
        help="Print document_context and section_context for each chunk",
    )
    args = parser.parse_args()

    conn = open_db(args.db)
    print(f"Database : {args.db}  ({args.db.stat().st_size / 1_000:.0f} KB)\n")

    if args.summary:
        show_summary(conn)

    if args.search:
        show_search(conn, args.search, args.limit)
    elif args.ticker and not args.section and not args.summary:
        show_sections(conn, args.ticker.upper())
    elif args.ticker or args.section:
        show_chunks(
            conn,
            ticker        = args.ticker.upper() if args.ticker else None,
            section       = args.section,
            limit         = args.limit,
            show_enriched = args.show_enriched,
            show_contexts = args.show_contexts,
        )
    elif not args.summary and not args.search:
        # No mode selected — print summary by default
        show_summary(conn)

    conn.close()


if __name__ == "__main__":
    main()
