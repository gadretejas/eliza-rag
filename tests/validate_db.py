#!/usr/bin/env python3
"""
Validates the contents of contextualized_chunks.db (or a test DB).

Runs a suite of checks and prints PASS / FAIL / WARN for each.
Exits with code 1 if any check fails.

Usage:
    python3 validate_db.py
    python3 validate_db.py --db contextualization_test_output.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from src.config import CONTEXTUALIZED_DB as DEFAULT_DB, TEST_DB_PATH as FALLBACK_DB

EXPECTED_CHUNKS    = 50_676
EXPECTED_DOCUMENTS = 246
EXPECTED_TICKERS   = 54


# ── Helpers ────────────────────────────────────────────────────────────────────

def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"Database not found: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


results: list[tuple[str, str, str]] = []   # (status, name, detail)


def check(name: str, passed: bool, detail: str = "", warn_only: bool = False) -> bool:
    status = "PASS" if passed else ("WARN" if warn_only else "FAIL")
    results.append((status, name, detail))
    symbol = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}[status]
    print(f"  {symbol}  {status:<4}  {name}")
    if detail:
        for line in detail.splitlines():
            print(f"            {line}")
    return passed


# ── Checks ─────────────────────────────────────────────────────────────────────

def run_checks(conn: sqlite3.Connection, full: bool) -> None:

    # ── 1. Row counts ──────────────────────────────────────────────────────────
    print("\n── Row counts ────────────────────────────────────────────────────────")

    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    if full:
        check("Total chunks == 50,676", total == EXPECTED_CHUNKS,
              f"got {total:,}")
    else:
        check("Total chunks > 0", total > 0, f"got {total:,}")

    n_docs = conn.execute(
        "SELECT COUNT(DISTINCT source_file) FROM chunks"
    ).fetchone()[0]
    if full:
        check("Distinct documents == 246", n_docs == EXPECTED_DOCUMENTS,
              f"got {n_docs}")
    else:
        check("Distinct documents > 0", n_docs > 0, f"got {n_docs}")

    n_tickers = conn.execute(
        "SELECT COUNT(DISTINCT ticker) FROM chunks"
    ).fetchone()[0]
    if full:
        check("Distinct tickers == 54", n_tickers == EXPECTED_TICKERS,
              f"got {n_tickers}")
    else:
        check("Distinct tickers > 0", n_tickers > 0, f"got {n_tickers}")

    # ── 2. ID uniqueness ───────────────────────────────────────────────────────
    print("\n── ID uniqueness ─────────────────────────────────────────────────────")

    dup_ids = conn.execute("""
        SELECT id, COUNT(*) as n FROM chunks GROUP BY id HAVING n > 1
    """).fetchall()
    check("No duplicate chunk IDs", len(dup_ids) == 0,
          f"{len(dup_ids)} duplicate IDs" if dup_ids else "")

    # ── 3. Context coverage ────────────────────────────────────────────────────
    print("\n── Context coverage ──────────────────────────────────────────────────")

    missing_doc = conn.execute("""
        SELECT COUNT(*) FROM chunks
        WHERE document_context IS NULL OR document_context = ''
    """).fetchone()[0]
    check("All chunks have document_context", missing_doc == 0,
          f"{missing_doc:,} chunks missing document_context", warn_only=True)

    missing_sec = conn.execute("""
        SELECT COUNT(*) FROM chunks
        WHERE section_context IS NULL OR section_context = ''
    """).fetchone()[0]
    check("All chunks have section_context", missing_sec == 0,
          f"{missing_sec:,} chunks missing section_context", warn_only=True)

    # ── 4. Enriched text structure ─────────────────────────────────────────────
    print("\n── Enriched text structure ───────────────────────────────────────────")

    no_doc_tag = conn.execute("""
        SELECT COUNT(*) FROM chunks
        WHERE enriched_text NOT LIKE '[DOCUMENT]%'
        AND document_context IS NOT NULL AND document_context != ''
    """).fetchone()[0]
    check("Enriched text starts with [DOCUMENT] tag", no_doc_tag == 0,
          f"{no_doc_tag:,} enriched chunks missing [DOCUMENT] prefix")

    no_sec_tag = conn.execute("""
        SELECT COUNT(*) FROM chunks
        WHERE enriched_text NOT LIKE '%[SECTION]%'
        AND section_context IS NOT NULL AND section_context != ''
    """).fetchone()[0]
    check("Enriched text contains [SECTION] tag", no_sec_tag == 0,
          f"{no_sec_tag:,} enriched chunks missing [SECTION] tag")

    shorter = conn.execute("""
        SELECT COUNT(*) FROM chunks
        WHERE LENGTH(enriched_text) <= LENGTH(original_text)
    """).fetchone()[0]
    check("Enriched text is longer than original", shorter == 0,
          f"{shorter:,} chunks where enriched_text <= original_text", warn_only=True)

    # ── 5. No empty text ───────────────────────────────────────────────────────
    print("\n── Empty text ────────────────────────────────────────────────────────")

    empty_orig = conn.execute("""
        SELECT COUNT(*) FROM chunks
        WHERE original_text IS NULL OR TRIM(original_text) = ''
    """).fetchone()[0]
    check("No empty original_text", empty_orig == 0,
          f"{empty_orig:,} chunks with empty original_text")

    empty_enr = conn.execute("""
        SELECT COUNT(*) FROM chunks
        WHERE enriched_text IS NULL OR TRIM(enriched_text) = ''
    """).fetchone()[0]
    check("No empty enriched_text", empty_enr == 0,
          f"{empty_enr:,} chunks with empty enriched_text")

    # ── 6. Chunk index continuity per document ─────────────────────────────────
    print("\n── Chunk index continuity ────────────────────────────────────────────")

    # Within each (source_file, section_id), chunk indices should be 0..n-1
    gaps = conn.execute("""
        SELECT source_file, section_id,
               COUNT(*)            AS n,
               MAX(chunk_index)    AS max_idx
        FROM chunks
        GROUP BY source_file, section_id
        HAVING MAX(chunk_index) != COUNT(*) - 1
    """).fetchall()
    check("Chunk indices are contiguous per (file, section)", len(gaps) == 0,
          f"{len(gaps)} (file, section) pairs have index gaps" if gaps else "",
          warn_only=True)

    # ── 7. Required metadata fields ────────────────────────────────────────────
    print("\n── Required metadata ─────────────────────────────────────────────────")

    for field in ("ticker", "company", "filing_type", "filing_date", "section_id"):
        n = conn.execute(
            f"SELECT COUNT(*) FROM chunks WHERE {field} IS NULL OR TRIM({field}) = ''"
        ).fetchone()[0]
        check(f"No null/empty {field}", n == 0,
              f"{n:,} chunks missing {field}")

    # ── 8. Token sanity ────────────────────────────────────────────────────────
    print("\n── Token sanity ──────────────────────────────────────────────────────")

    very_short = conn.execute("""
        SELECT COUNT(*) FROM chunks WHERE LENGTH(original_text) < 50
    """).fetchone()[0]
    check("No suspiciously short chunks (< 50 chars)", very_short == 0,
          f"{very_short:,} chunks under 50 chars", warn_only=True)

    row = conn.execute("""
        SELECT AVG(LENGTH(original_text) / 4) AS avg_orig,
               AVG(LENGTH(enriched_text)  / 4) AS avg_enr,
               MIN(LENGTH(original_text) / 4) AS min_orig,
               MAX(LENGTH(original_text) / 4) AS max_orig
        FROM chunks
    """).fetchone()
    check(
        "Average token counts in expected range",
        300 <= row["avg_orig"] <= 700,
        f"avg_original={row['avg_orig']:.0f}  avg_enriched={row['avg_enr']:.0f}  "
        f"min={row['min_orig']}  max={row['max_orig']}",
        warn_only=True,
    )

    # ── 9. Filing type distribution ────────────────────────────────────────────
    print("\n── Filing type distribution ──────────────────────────────────────────")

    rows = conn.execute("""
        SELECT SUBSTR(filing_type, 1, 4) AS ftype,
               COUNT(DISTINCT source_file) AS docs,
               COUNT(*) AS chunks
        FROM chunks
        GROUP BY ftype
        ORDER BY docs DESC
    """).fetchall()
    detail = "  ".join(f"{r['ftype']} — {r['docs']} docs, {r['chunks']:,} chunks"
                       for r in rows)
    has_10k  = any(r["ftype"] == "10-K" for r in rows)
    has_10q  = any(r["ftype"] == "10-Q" for r in rows)
    check("Both 10-K and 10-Q filings present", has_10k and has_10q, detail)

    # ── 10. Content type split ─────────────────────────────────────────────────
    print("\n── Content type ──────────────────────────────────────────────────────")

    rows = conn.execute("""
        SELECT content_type, COUNT(*) as n FROM chunks
        GROUP BY content_type ORDER BY n DESC
    """).fetchall()
    detail = "  ".join(f"{r['content_type']}={r['n']:,}" for r in rows)
    valid_types = {r["content_type"] for r in rows} <= {"text", "table"}
    check("Only valid content_type values (text / table)", valid_types, detail)


# ── Summary ────────────────────────────────────────────────────────────────────

def print_summary() -> int:
    passed = sum(1 for s, _, _ in results if s == "PASS")
    warned = sum(1 for s, _, _ in results if s == "WARN")
    failed = sum(1 for s, _, _ in results if s == "FAIL")

    print(f"\n── Result ────────────────────────────────────────────────────────────")
    print(f"  {passed} passed  {warned} warnings  {failed} failed")

    if failed:
        print("\nFailed checks:")
        for s, name, detail in results:
            if s == "FAIL":
                print(f"  ✗ {name}")
                if detail:
                    print(f"    {detail}")

    return failed


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    default_db = DEFAULT_DB if DEFAULT_DB.exists() else FALLBACK_DB

    parser = argparse.ArgumentParser(
        description="Validate a contextualized_chunks.db database"
    )
    parser.add_argument(
        "--db", type=Path, default=default_db,
        help=f"Path to the SQLite database (default: {default_db})",
    )
    args = parser.parse_args()

    conn = open_db(args.db)
    size_mb = args.db.stat().st_size / 1e6
    full = args.db.name == DEFAULT_DB.name

    print(f"Database : {args.db}  ({size_mb:.0f} MB)")
    if not full:
        print("  (test DB — skipping full corpus count assertions)")

    run_checks(conn, full=full)
    conn.close()

    failed = print_summary()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
