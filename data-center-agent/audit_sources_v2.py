#!/usr/bin/env python3
"""Source-resolution audit using pipeline-equivalent extraction.

For each source, runs the same text extraction and chunking as the real pipeline,
then applies dual labels: source_resolution_status + extraction_eligibility.
"""

import csv
import json
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.agents.content_quality import classify_content_quality, compute_strong_keyword_score
from app.agents.parser import chunk_text_by_tokens, count_tokens_rough
from app.db.connection import get_engine
from sqlalchemy import text

OUTPUT_DIR = Path("/data/hermes/audits")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CSV = OUTPUT_DIR / "source_resolution_audit_v2.csv"
OUTPUT_JSON = OUTPUT_DIR / "source_resolution_audit_v2.json"

TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; InternUpAudit/1.0; +https://internup.org)"
}
TARGET_TOKENS = 1000
MIN_TOKENS = 800
MAX_TOKENS = 1200


def classify_url(url: str) -> str:
    lower = url.lower()
    if lower.endswith(".pdf") or "/pdf/" in lower:
        return "direct_pdf"
    if lower.endswith((".xlsx", ".xlsm", ".csv", ".xls")):
        return "direct_xlsx_csv"
    return "unknown"


def extract_candidate_links(html: str, url: str) -> dict:
    """Extract PDF, dataset, and API links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    pdf_links, dataset_links, api_links = [], [], []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(url, href)
        href_lower = href.lower()

        if href_lower.endswith(".pdf") or "pdf" in href_lower:
            pdf_links.append(full_url)
        if href_lower.endswith((".xlsx", ".xlsm", ".xls", ".csv")):
            dataset_links.append(full_url)
        if any(term in href_lower for term in ["/api/", "data.gov", "download"]):
            if href_lower.endswith((".json", ".csv", ".xlsx")):
                api_links.append(full_url)

    return {
        "pdfs": list(set(pdf_links))[:10],
        "datasets": list(set(dataset_links))[:5],
        "apis": list(set(api_links))[:5],
    }


def pipeline_extract_and_chunk(text_content: str) -> tuple[list[dict], list[str]]:
    """Run the same chunking logic as the real pipeline.

    Returns (chunks, chunk_texts).
    """
    if not text_content or not text_content.strip():
        return [], []

    chunks_raw = chunk_text_by_tokens(text_content, TARGET_TOKENS, MIN_TOKENS, MAX_TOKENS)
    chunk_texts = [c for c in chunks_raw]
    return chunks_raw, chunk_texts


def audit_source(source_id: str, url: str, source_type: str, crawl_status: str,
                 raw_file_path: str, title: str) -> dict:
    """Audit a single source using pipeline-equivalent extraction."""
    row = {
        "source_id": source_id,
        "original_url": url,
        "source_type": source_type,
        "title": title or "",
        "crawl_status": crawl_status,
        "http_status": "",
        "content_type": "",
        "char_count": 0,
        "chunk_count": 0,
        "keyword_score": 0.0,
        "keyword_hits": "",
        "candidate_pdfs": "",
        "candidate_datasets": "",
        "candidate_apis": "",
        "content_quality_score": 0.0,
        "source_resolution_status": "",
        "extraction_eligibility": "",
        "recommended_next_action": "",
        "skip_reason_codes": "",
        "notes": "",
    }

    # --- Already processed with raw file ---
    if raw_file_path and crawl_status == "parsed":
        raw_path = Path("/data/hermes") / raw_file_path
        if raw_path.exists():
            try:
                content = raw_path.read_text(errors="ignore")
                if raw_path.suffix == ".html":
                    text_content = trafilatura.extract(content) or ""
                    row["content_type"] = "text/html"
                else:
                    text_content = content
                    row["content_type"] = "application/pdf"

                row["char_count"] = len(text_content)
                row["http_status"] = 200

                # Pipeline-equivalent chunking
                _, chunk_texts = pipeline_extract_and_chunk(text_content)
                row["chunk_count"] = len(chunk_texts)

                # Keyword analysis
                combined = "\n".join(chunk_texts)
                kw_score, kw_hits = compute_strong_keyword_score(combined)
                row["keyword_score"] = kw_score
                row["keyword_hits"] = "|".join(kw_hits[:5])

                # Build fake chunks for quality classification
                fake_chunks = [{"chunk_text": t} for t in chunk_texts]
                quality = classify_content_quality(
                    fake_chunks,
                    source_type=source_type,
                    crawl_status=crawl_status,
                )
                row["content_quality_score"] = kw_score
                row["source_resolution_status"] = quality.source_resolution_status
                row["extraction_eligibility"] = quality.extraction_eligibility

                if source_type == "pdf":
                    row["recommended_next_action"] = "process_directly"
                elif quality.extraction_eligibility in ("eligible", "eligible_conditional"):
                    row["recommended_next_action"] = "process_directly"
                elif quality.extraction_eligibility == "ineligible_gated":
                    row["recommended_next_action"] = "mark_paywalled"
                elif quality.extraction_eligibility == "ineligible_low_text":
                    row["recommended_next_action"] = "skip_low_text"
                else:
                    row["recommended_next_action"] = "browser_resolution_needed"

                row["notes"] = f"pipeline-equivalent: {quality.extraction_eligibility}"

            except Exception as e:
                row["notes"] = f"Error: {str(e)[:100]}"
                row["source_resolution_status"] = "failed"
                row["extraction_eligibility"] = "ineligible_failed"
                row["recommended_next_action"] = "mark_failed"
        else:
            row["notes"] = "Raw file not found"
            if source_type == "pdf":
                row["source_resolution_status"] = "pending"
                row["extraction_eligibility"] = "eligible"
                row["recommended_next_action"] = "process_directly"
            else:
                row["source_resolution_status"] = "pending"
                row["extraction_eligibility"] = "ineligible_low_text"
                row["recommended_next_action"] = "browser_resolution_needed"
        return row

    # --- Paywalled ---
    if crawl_status == "private_or_paywalled":
        row["http_status"] = 403
        row["source_resolution_status"] = "paywalled_or_gated"
        row["extraction_eligibility"] = "ineligible_gated"
        row["recommended_next_action"] = "mark_paywalled"
        return row

    # --- URL-based classification ---
    url_class = classify_url(url)
    if url_class == "direct_pdf":
        row["source_resolution_status"] = "pending"
        row["extraction_eligibility"] = "eligible"
        row["recommended_next_action"] = "process_directly"
        # Check HTTP status
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS) as client:
                resp = client.head(url)
                row["http_status"] = resp.status_code
                row["content_type"] = resp.headers.get("content-type", "").split(";")[0]
        except httpx.HTTPStatusError as e:
            row["http_status"] = e.response.status_code
            if e.response.status_code in (401, 403):
                row["source_resolution_status"] = "paywalled_or_gated"
                row["extraction_eligibility"] = "ineligible_gated"
                row["recommended_next_action"] = "mark_paywalled"
            elif e.response.status_code == 404:
                row["source_resolution_status"] = "failed"
                row["extraction_eligibility"] = "ineligible_failed"
                row["recommended_next_action"] = "mark_failed"
        except Exception as e:
            row["notes"] = f"HTTP error: {str(e)[:100]}"
            row["source_resolution_status"] = "failed"
            row["extraction_eligibility"] = "ineligible_failed"
            row["recommended_next_action"] = "mark_failed"
        return row

    if url_class == "direct_xlsx_csv":
        row["source_resolution_status"] = "pending"
        row["extraction_eligibility"] = "eligible"
        row["recommended_next_action"] = "create_child_dataset_source"
        return row

    # --- HTML source — fetch, extract, chunk, classify ---
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS) as client:
            resp = client.get(url)
            row["http_status"] = resp.status_code
            row["content_type"] = resp.headers.get("content-type", "").split(";")[0]

            if resp.status_code in (401, 403):
                row["source_resolution_status"] = "paywalled_or_gated"
                row["extraction_eligibility"] = "ineligible_gated"
                row["recommended_next_action"] = "mark_paywalled"
                return row
            if resp.status_code >= 400:
                row["source_resolution_status"] = "failed"
                row["extraction_eligibility"] = "ineligible_failed"
                row["recommended_next_action"] = "mark_failed"
                return row

            # Extract text using trafilatura (same as pipeline)
            html_content = resp.text
            text_content = trafilatura.extract(html_content) or ""
            row["char_count"] = len(text_content)

            # Pipeline-equivalent chunking
            _, chunk_texts = pipeline_extract_and_chunk(text_content)
            row["chunk_count"] = len(chunk_texts)

            # Candidate links
            links = extract_candidate_links(html_content, url)
            row["candidate_pdfs"] = "|".join(links["pdfs"][:5])
            row["candidate_datasets"] = "|".join(links["datasets"][:3])
            row["candidate_apis"] = "|".join(links["apis"][:3])

            # Keyword analysis
            combined = "\n".join(chunk_texts)
            kw_score, kw_hits = compute_strong_keyword_score(combined)
            row["keyword_score"] = kw_score
            row["keyword_hits"] = "|".join(kw_hits[:5])

            # Quality classification
            fake_chunks = [{"chunk_text": t} for t in chunk_texts]
            quality = classify_content_quality(
                fake_chunks,
                source_type=source_type,
                crawl_status=crawl_status,
            )
            row["content_quality_score"] = kw_score
            row["source_resolution_status"] = quality.source_resolution_status
            row["extraction_eligibility"] = quality.extraction_eligibility
            row["skip_reason_codes"] = quality.eligibility_reason if quality.extraction_eligibility.startswith("ineligible") else ""

            # Recommended action
            if quality.extraction_eligibility in ("eligible", "eligible_conditional"):
                row["recommended_next_action"] = "process_directly"
            elif quality.extraction_eligibility == "ineligible_gated":
                if links["pdfs"]:
                    row["recommended_next_action"] = "create_child_pdf_source"
                else:
                    row["recommended_next_action"] = "mark_paywalled"
            elif quality.extraction_eligibility == "ineligible_low_text":
                if links["pdfs"]:
                    row["recommended_next_action"] = "create_child_pdf_source"
                else:
                    row["recommended_next_action"] = "skip_low_text"
            else:
                row["recommended_next_action"] = "browser_resolution_needed"

    except httpx.TimeoutException:
        row["notes"] = "Request timed out"
        row["source_resolution_status"] = "failed"
        row["extraction_eligibility"] = "ineligible_failed"
        row["recommended_next_action"] = "mark_failed"
    except httpx.RequestError as e:
        row["notes"] = f"Request failed: {str(e)[:100]}"
        row["source_resolution_status"] = "failed"
        row["extraction_eligibility"] = "ineligible_failed"
        row["recommended_next_action"] = "mark_failed"
    except Exception as e:
        row["notes"] = f"Error: {str(e)[:100]}"
        row["source_resolution_status"] = "unknown"
        row["extraction_eligibility"] = "ineligible_low_text"
        row["recommended_next_action"] = "browser_resolution_needed"

    return row


def main():
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id::text, original_url, source_type, crawl_status,
                   raw_file_path, title
            FROM sources
            ORDER BY source_type, id
        """))
        sources = result.fetchall()

    print(f"Auditing {len(sources)} sources with pipeline-equivalent extraction...")
    rows = []
    start = time.time()

    for i, src in enumerate(sources):
        source_id, url, source_type, crawl_status, raw_file_path, title = src
        if i % 20 == 0 and i > 0:
            elapsed = time.time() - start
            rate = i / elapsed
            eta = (len(sources) - i) / rate
            print(f"  [{i}/{len(sources)}] {rate:.1f}/s, ETA {eta:.0f}s")

        row = audit_source(source_id, url, source_type, crawl_status, raw_file_path, title)
        rows.append(row)

    elapsed = time.time() - start
    print(f"Audit complete in {elapsed:.1f}s")

    # Write CSV
    fieldnames = [
        "source_id", "original_url", "source_type", "title", "crawl_status",
        "http_status", "content_type", "char_count", "chunk_count",
        "keyword_score", "keyword_hits",
        "candidate_pdfs", "candidate_datasets", "candidate_apis",
        "content_quality_score", "source_resolution_status", "extraction_eligibility",
        "recommended_next_action", "skip_reason_codes", "notes",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Write JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nAudit saved to:\n  CSV: {OUTPUT_CSV}\n  JSON: {OUTPUT_JSON}")

    # Summary
    from collections import Counter
    res_counts = Counter(r["source_resolution_status"] for r in rows)
    elig_counts = Counter(r["extraction_eligibility"] for r in rows)
    action_counts = Counter(r["recommended_next_action"] for r in rows)

    print("\n=== Source Resolution Status ===")
    for status, count in res_counts.most_common():
        print(f"  {status:30s} {count:4d}")

    print("\n=== Extraction Eligibility ===")
    for elig, count in elig_counts.most_common():
        print(f"  {elig:30s} {count:4d}")

    print("\n=== Recommended Actions ===")
    for action, count in action_counts.most_common():
        print(f"  {action:30s} {count:4d}")

    # Keyword stats for eligible sources
    eligible = [r for r in rows if r["extraction_eligibility"] in ("eligible", "eligible_conditional")]
    conditional = [r for r in rows if r["extraction_eligibility"] == "eligible_conditional"]
    print(f"\n=== Keyword Analysis ===")
    print(f"  Eligible sources: {len(eligible)}")
    print(f"  Conditional (low text + strong keywords): {len(conditional)}")
    for r in conditional[:10]:
        print(f"    score={r['keyword_score']:5.1f}  chunks={r['chunk_count']}  {r['original_url'][:60]}")


if __name__ == "__main__":
    main()
