#!/usr/bin/env python3
"""Batch ingest new PDFs from /home/ubuntu/report/ into Venture-Metrics-db."""
import os
import sys
import uuid
import json
from pathlib import Path
from datetime import datetime

from sqlalchemy import text
from app.db.connection import get_engine

REPORT_DIR = Path("/home/ubuntu/report")
GEO_MAP = {
    "美国": "United States",
    "英国": "United Kingdom",
    "新加坡": "Singapore",
    "国内": "China",
}

def main():
    engine = get_engine()

    # Get existing local PDF paths
    with engine.connect() as conn:
        r = conn.execute(text("SELECT original_url FROM sources WHERE original_url LIKE '/home/ubuntu/report/%'"))
        existing_paths = {row[0] for row in r.fetchall()}

    # Scan PDFs
    pdfs = []
    for root, dirs, files in os.walk(REPORT_DIR):
        for f in sorted(files):
            if f.lower().endswith(".pdf"):
                full = os.path.join(root, f)
                geo_folder = os.path.relpath(full, REPORT_DIR).split(os.sep)[0]
                pdfs.append({"path": full, "filename": f, "geography": GEO_MAP.get(geo_folder)})

    # Filter to new only
    new_pdfs = [p for p in pdfs if p["path"] not in existing_paths]
    print(f"Total on disk: {len(pdfs)}, Already ingested: {len(existing_paths)}, New to ingest: {len(new_pdfs)}")

    if not new_pdfs:
        print("Nothing new to ingest.")
        return

    # Import workers
    from app.workers.process_source import process_source
    from app.workers.process_report import process_report

    success = 0
    failed = []
    skipped = []

    for i, pdf in enumerate(new_pdfs, 1):
        source_id = uuid.uuid4()
        fname = pdf["filename"]
        print(f"\n[{i}/{len(new_pdfs)}] {fname}")

        try:
            # Insert source
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO sources (id, original_url, source_type, crawl_status, notes)
                    VALUES (:id, :url, 'pdf', 'pending', :notes)
                """), {"id": source_id, "url": pdf["path"], "notes": "Batch local ingest 2026-05-29"})

            # Fetch + store
            result = process_source(source_id)
            crawl_status = result["source"].get("crawl_status")
            if crawl_status != "fetched":
                failed.append((fname, f"fetch status: {crawl_status}"))
                print(f"  FAILED: fetch status = {crawl_status}")
                continue

            # Get report
            report = result.get("report")
            if not report:
                with engine.connect() as conn:
                    r = conn.execute(text("SELECT id FROM reports WHERE source_id = :sid"), {"sid": source_id})
                    row = r.fetchone()
                    if not row:
                        failed.append((fname, "no report created"))
                        print(f"  FAILED: no report created")
                        continue
                    report_id = row[0]
            else:
                report_id = report["id"]

            # Parse into chunks
            try:
                chunk_result = process_report(report_id)
                chunk_count = chunk_result if isinstance(chunk_result, int) else len(chunk_result) if chunk_result else 0
            except Exception as e:
                chunk_count = 0
                print(f"  Warning: process_report error: {e}")

            # Set geography
            if pdf["geography"]:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE reports SET geography = :geo WHERE id = :id"),
                                {"geo": pdf["geography"], "id": report_id})

            success += 1
            print(f"  OK: source={source_id}, report={report_id}, chunks={chunk_count}")

        except Exception as e:
            err = str(e)[:300]
            failed.append((fname, err))
            print(f"  EXCEPTION: {err}")

    print(f"\n{'='*60}")
    print(f"RESULTS: {success} success, {len(failed)} failed, {len(skipped)} skipped")
    if failed:
        print("\nFailed PDFs:")
        for fname, reason in failed:
            print(f"  {fname}: {reason}")

    # Write summary
    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_on_disk": len(pdfs),
        "already_ingested": len(existing_paths),
        "new_attempted": len(new_pdfs),
        "success": success,
        "failed": len(failed),
        "failures": [{"file": f, "reason": r} for f, r in failed],
    }
    summary_path = Path("/home/ubuntu/Venture-Metrics-db/data-center-agent/ingest_batch_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSummary written to {summary_path}")


if __name__ == "__main__":
    main()
