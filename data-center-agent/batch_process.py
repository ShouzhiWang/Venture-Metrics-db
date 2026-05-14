#!/usr/bin/env python3
"""Batch process ready sources: process_source → process_report → generate_codebook --dry-run."""

import json
import sys
import time
import traceback
from pathlib import Path
from uuid import UUID

from app.db.connection import get_engine
from app.workers.process_source import process_source
from app.workers.process_report import process_report
from app.workers.generate_codebook import generate_codebook
from sqlalchemy import text


def get_ready_sources(engine):
    """Get sources that are ready to process (process_directly action, not yet processed)."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT s.id::text, s.original_url, s.source_type, s.title
            FROM sources s
            WHERE s.crawl_status = 'pending'
              AND s.source_type IN ('html', 'pdf')
              AND s.original_url NOT IN (
                  -- Skip known paywalled domains
                  'https://pitchbook.com/news/reports/q3-2025-pitchbook-nvca-venture-monitor-q3-2025',
                  'https://carta.com/data/state-of-private-markets-q3-2025/'
              )
            ORDER BY s.source_type, s.id
        """))
        return result.fetchall()


def process_one(source_id_str, engine):
    """Process a single source through the full pipeline."""
    source_id = UUID(source_id_str)
    result = {
        "source_id": source_id_str,
        "status": "pending",
        "report_id": None,
        "title": None,
        "chunks": 0,
        "codebook_skipped": False,
        "codebook_skip_reason": None,
        "candidate_chunks": 0,
        "final_variables": 0,
        "needs_review": 0,
        "private": 0,
        "error": None,
    }

    try:
        # Step 1: process_source
        src_result = process_source(source_id)
        report = src_result.get("report")
        if not report:
            result["status"] = "no_report"
            result["error"] = "No report created (likely fetch failed or dataset)"
            return result

        report_id = UUID(report["id"]) if isinstance(report["id"], str) else report["id"]
        result["report_id"] = str(report_id)
        result["title"] = report.get("title")

        # Step 2: process_report
        chunk_count = process_report(report_id)
        result["chunks"] = chunk_count

        if chunk_count == 0:
            result["status"] = "no_chunks"
            return result

        # Step 3: generate_codebook --dry-run
        codebook = generate_codebook(report_id, dry_run=True, top_k=40)
        summary = codebook.get("summary", {})

        if summary.get("skipped"):
            result["codebook_skipped"] = True
            result["codebook_skip_reason"] = summary.get("skip_reason")
            result["status"] = "processed_skip"
            return result

        result["candidate_chunks"] = summary.get("candidate_chunks", 0)
        result["final_variables"] = summary.get("final_variables", 0)
        result["needs_review"] = summary.get("needs_review", 0)
        result["private"] = summary.get("private", 0)
        result["status"] = "processed"
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return result


def main():
    engine = get_engine()
    sources = get_ready_sources(engine)
    print(f"Found {len(sources)} ready sources to process")
    print()

    results = []
    start = time.time()

    for i, src in enumerate(sources):
        source_id_str = src[0]
        url = src[1][:60]
        source_type = src[2]

        elapsed = time.time() - start
        rate = (i + 1) / elapsed if elapsed > 0 else 0
        eta = (len(sources) - i - 1) / rate if rate > 0 else 0

        print(f"[{i+1}/{len(sources)}] {source_type:4s} {url:60s} (ETA {eta:.0f}s)", end="", flush=True)

        result = process_one(source_id_str, engine)
        results.append(result)

        status = result["status"]
        if status == "processed":
            print(f" ✓ {result['chunks']} chunks, {result['final_variables']} vars")
        elif status == "processed_skip":
            print(f" ⏭ {result['codebook_skip_reason']}")
        elif status == "no_report":
            print(f" ✗ no report ({result.get('error', '')[:50]})")
        elif status == "no_chunks":
            print(f" ⚠ 0 chunks")
        else:
            print(f" ✗ {result.get('error', 'unknown')[:60]}")

    elapsed = time.time() - start
    print(f"\nBatch complete in {elapsed:.1f}s")

    # Summary
    from collections import Counter
    status_counts = Counter(r["status"] for r in results)
    print("\n=== Status Summary ===")
    for status, count in status_counts.most_common():
        print(f"  {status:20s} {count:3d}")

    processed = [r for r in results if r["status"] == "processed"]
    skipped = [r for r in results if r["status"] == "processed_skip"]
    total_vars = sum(r["final_variables"] for r in processed)
    total_private = sum(r["private"] for r in processed)
    total_chunks = sum(r["chunks"] for r in results if r["chunks"] > 0)

    print(f"\n=== Totals ===")
    print(f"  Sources processed: {len(processed)}")
    print(f"  Sources skipped by quality gate: {len(skipped)}")
    print(f"  Total chunks: {total_chunks}")
    print(f"  Total variables (dry-run): {total_vars}")
    print(f"  Total private: {total_private}")
    print(f"  Total needs_review: {sum(r['needs_review'] for r in processed)}")

    # Save results
    output = Path("/data/hermes/audits/batch_processing_results.json")
    with open(output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output}")


if __name__ == "__main__":
    main()
