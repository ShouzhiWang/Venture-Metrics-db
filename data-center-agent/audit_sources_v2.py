#!/usr/bin/env python3
"""Source-resolution audit using pipeline-equivalent extraction.

For each source, runs the same text extraction and chunking as the real pipeline,
then applies dual labels: source_resolution_status + extraction_eligibility.
"""

import csv
import json
import time
from pathlib import Path

import httpx
import trafilatura

from app.agents.content_quality import classify_content_quality, compute_strong_keyword_score
from app.agents.parser import chunk_text_by_tokens, count_tokens_rough
from app.agents.source_resolver import SourceResolver
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
        return "direct_dataset"
    return "unknown"


def extract_candidate_links(html: str, url: str) -> dict:
    """Extract ranked downloadable artifact candidates from HTML."""
    artifacts = SourceResolver().discover_artifacts(html, url)
    pdfs = [artifact for artifact in artifacts if artifact.artifact_type == "pdf"]
    datasets = [artifact for artifact in artifacts if artifact.artifact_type == "dataset_file"]
    top = artifacts[0] if artifacts else None

    return {
        "pdfs": [artifact.url for artifact in pdfs[:10]],
        "datasets": [artifact.url for artifact in datasets[:5]],
        "apis": [],
        "candidate_pdf_count": len(pdfs),
        "top_candidate_url": top.url if top else "",
        "top_candidate_score": top.score if top else "",
        "top_candidate_link_text": top.link_text if top else "",
    }


def classify_html_source_kind(html: str, url: str, quality_status: str, links: dict) -> str:
    signals = SourceResolver().inspect_html(html)
    lowered = html.lower()
    news_hits = sum(1 for term in ("news", "article", "blog", "press release", "announced") if term in lowered)
    report_hits = sum(1 for term in ("methodology", "data source", "defined as", "technical notes", "appendix") if term in lowered)
    if signals.status == "gated_or_paywalled" or quality_status == "paywalled_or_gated":
        return "gated_or_paywalled"
    if signals.status == "needs_browser" or quality_status == "js_required":
        return "needs_browser"
    if links["pdfs"]:
        return "html_landing_with_pdf_candidate"
    if links["datasets"]:
        return "html_landing_with_dataset_candidate"
    if news_hits >= 2 and report_hits < 2:
        return "news_article"
    if quality_status in {"full_report", "partial_report", "low_text"} and report_hits >= 2:
        return "html_full_report"
    return "html_landing_no_artifact"


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
        "candidate_pdf_count": 0,
        "top_candidate_url": "",
        "top_candidate_score": "",
        "top_candidate_link_text": "",
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
                row["source_resolution_status"] = "direct_pdf" if source_type == "pdf" else quality.source_resolution_status
                row["extraction_eligibility"] = quality.extraction_eligibility

                if source_type == "pdf":
                    row["recommended_next_action"] = "process_direct_pdf"
                elif quality.extraction_eligibility in ("eligible", "eligible_conditional"):
                    row["recommended_next_action"] = "process_html_report"
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
        row["source_resolution_status"] = "direct_pdf"
        row["extraction_eligibility"] = "eligible"
        row["recommended_next_action"] = "process_direct_pdf"
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

    if url_class == "direct_dataset":
        row["source_resolution_status"] = "direct_dataset"
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
            row["candidate_pdf_count"] = links["candidate_pdf_count"]
            row["top_candidate_url"] = links["top_candidate_url"]
            row["top_candidate_score"] = links["top_candidate_score"]
            row["top_candidate_link_text"] = links["top_candidate_link_text"]

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
            row["source_resolution_status"] = classify_html_source_kind(
                html_content,
                url,
                quality.source_resolution_status,
                links,
            )
            row["extraction_eligibility"] = quality.extraction_eligibility
            row["skip_reason_codes"] = quality.eligibility_reason if quality.extraction_eligibility.startswith("ineligible") else ""

            # Recommended action
            if row["source_resolution_status"] == "html_landing_with_pdf_candidate":
                row["recommended_next_action"] = "create_child_pdf_source"
            elif row["source_resolution_status"] == "html_landing_with_dataset_candidate":
                row["recommended_next_action"] = "create_child_dataset_source"
            elif row["source_resolution_status"] == "html_full_report":
                row["recommended_next_action"] = "process_html_report"
            elif row["source_resolution_status"] == "gated_or_paywalled":
                row["recommended_next_action"] = "manual_download_needed"
            elif row["source_resolution_status"] == "needs_browser":
                row["recommended_next_action"] = "browser_resolution_needed"
            elif row["source_resolution_status"] == "news_article":
                row["recommended_next_action"] = "skip_news_article"
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
        "candidate_pdf_count", "top_candidate_url", "top_candidate_score", "top_candidate_link_text",
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
