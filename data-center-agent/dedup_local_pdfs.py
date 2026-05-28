#!/usr/bin/env python3
"""Remove duplicate local PDF sources that overlap with existing web-sourced reports."""
import sys
from difflib import SequenceMatcher
from sqlalchemy import text
from app.db.connection import get_engine


def normalize_title(t):
    if not t:
        return ""
    t = t.lower().strip()
    for noise in [
        "| stanford hai", " - a16z", " | stanford graduate school of business",
        " | nsf - u.s. national science foundation", " | uob singapore",
    ]:
        t = t.replace(noise, "")
    return " ".join(t.split())


def title_similarity(a, b):
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def main():
    engine = get_engine()
    dry_run = "--dry-run" in sys.argv

    with engine.connect() as conn:
        # Get all local PDF sources with their reports
        r = conn.execute(text("""
            SELECT s.id as source_id, s.original_url, r.id as report_id, r.title
            FROM sources s
            JOIN reports r ON r.source_id = s.id
            WHERE s.original_url LIKE '/home/ubuntu/report/%'
            AND s.notes LIKE '%Batch%ingest%'
        """))
        pdf_sources = [
            {"source_id": row[0], "url": row[1], "report_id": row[2], "title": row[3]}
            for row in r.fetchall()
        ]

        # Get all web-sourced report titles
        r = conn.execute(text("""
            SELECT r.id, r.title
            FROM reports r
            JOIN sources s ON s.id = r.source_id
            WHERE s.original_url NOT LIKE '/home/ubuntu/report/%'
            AND r.title IS NOT NULL
        """))
        web_reports = [(row[0], row[1]) for row in r.fetchall()]

    print(f"Local PDF sources: {len(pdf_sources)}")
    print(f"Web-sourced reports: {len(web_reports)}")

    # Find duplicates
    duplicates = []
    unique = []
    for pdf in pdf_sources:
        if not pdf["title"]:
            unique.append(pdf)
            continue
        best_score = 0
        best_match = None
        for web_id, web_title in web_reports:
            score = title_similarity(pdf["title"], web_title)
            if score > best_score:
                best_score = score
                best_match = web_title
        if best_score >= 0.72:
            duplicates.append({
                **pdf,
                "match_title": best_match,
                "score": best_score,
            })
        else:
            unique.append(pdf)

    print(f"\nDuplicates (fuzzy match >= 0.65): {len(duplicates)}")
    print(f"Unique (no web match): {len(unique)}")

    if not duplicates:
        print("Nothing to deduplicate.")
        return

    print(f"\n{'='*60}")
    print("DUPLICATES TO REMOVE:")
    for d in sorted(duplicates, key=lambda x: -x["score"]):
        print(f"  {d['score']:.2f} | {d['title'][:60]}")
        print(f"       matched: {d['match_title'][:60]}")

    if dry_run:
        print(f"\n[DRY RUN] Would remove {len(duplicates)} local PDF sources + their reports/chunks.")
        return

    # Delete duplicates: chunks → report_variables → reports → sources
    with engine.begin() as conn:
        for d in duplicates:
            # Delete chunks
            conn.execute(text("DELETE FROM document_chunks WHERE report_id = :rid"),
                        {"rid": d["report_id"]})
            # Delete report variables
            conn.execute(text("DELETE FROM report_variables WHERE report_id = :rid"),
                        {"rid": d["report_id"]})
            # Delete search index entries
            conn.execute(text("DELETE FROM search_index WHERE object_id = :oid AND object_type IN ('source', 'report', 'variable', 'chunk')"),
                        {"oid": d["report_id"]})
            conn.execute(text("DELETE FROM search_index WHERE object_id = :oid AND object_type = 'source'"),
                        {"oid": d["source_id"]})
            # Delete report
            conn.execute(text("DELETE FROM reports WHERE id = :rid"),
                        {"rid": d["report_id"]})
            # Delete source
            conn.execute(text("DELETE FROM sources WHERE id = :sid"),
                        {"sid": d["source_id"]})

    print(f"\nRemoved {len(duplicates)} duplicate local PDF sources.")
    print(f"Remaining unique local PDFs: {len(unique)}")

    # Summary
    with engine.connect() as conn:
        r = conn.execute(text("SELECT COUNT(*) FROM sources"))
        print(f"Total sources now: {r.scalar()}")
        r = conn.execute(text("SELECT COUNT(*) FROM reports"))
        print(f"Total reports now: {r.scalar()}")
        r = conn.execute(text("SELECT COUNT(*) FROM document_chunks"))
        print(f"Total chunks now: {r.scalar()}")


if __name__ == "__main__":
    main()
