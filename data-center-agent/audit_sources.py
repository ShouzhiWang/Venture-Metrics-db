#!/usr/bin/env python3
"""Source-resolution audit: classify all sources and recommend next actions."""

import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.db.connection import get_engine
from sqlalchemy import text

OUTPUT_DIR = Path("/data/hermes/audits")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CSV = OUTPUT_DIR / "source_resolution_audit.csv"

TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; InternUpAudit/1.0; +https://internup.org)"
}


def classify_url(url: str) -> str:
    """Classify based on URL pattern alone."""
    lower = url.lower()
    if lower.endswith(".pdf") or "/pdf/" in lower:
        return "direct_pdf"
    if lower.endswith((".xlsx", ".xlsm", ".csv", ".xls")):
        return "direct_xlsx_csv"
    return "unknown"


def classify_content(html: str, url: str, content_type: str) -> dict:
    """Classify HTML content and extract candidate links."""
    lowered = html.lower()
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

    result = {
        "detected_source_kind": "unknown",
        "candidate_pdfs": [],
        "candidate_datasets": [],
        "candidate_apis": [],
    }

    # Check for paywall/gated indicators
    paywall_terms = [
        "subscribe", "subscription", "register to read", "members only",
        "paywall", "sign in to view", "login to read", "access denied",
        "permission denied", "premium content", "subscriber only",
    ]
    if any(term in lowered for term in paywall_terms):
        result["detected_source_kind"] = "paywalled_or_gated"
        return result

    # Check for JS-required indicators
    js_terms = ["enable javascript", "requires javascript", "javascript is disabled"]
    if any(term in lowered for term in js_terms) and len(html) < 5000:
        result["detected_source_kind"] = "js_required"
        return result

    # Extract links
    soup = BeautifulSoup(html, "html.parser")
    pdf_links = []
    dataset_links = []
    api_links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(url, href)
        href_lower = href.lower()
        link_text = (a_tag.get_text() or "").strip().lower()

        if href_lower.endswith(".pdf") or "pdf" in href_lower:
            pdf_links.append(full_url)
        if href_lower.endswith((".xlsx", ".xlsm", ".xls", ".csv")):
            dataset_links.append(full_url)
        if any(term in href_lower for term in ["/api/", "data.gov", "download"]):
            if href_lower.endswith((".json", ".csv", ".xlsx")):
                api_links.append(full_url)

    result["candidate_pdfs"] = list(set(pdf_links))[:10]
    result["candidate_datasets"] = list(set(dataset_links))[:5]
    result["candidate_apis"] = list(set(api_links))[:5]

    # Check trafilatura extraction
    extracted = trafilatura.extract(html) or ""
    text_len = len(extracted)

    # Check for report-like content
    report_terms = [
        "methodology", "data source", "defined as", "measured as",
        "appendix", "technical notes", "executive summary", "findings",
        "survey", "sample size", "confidence interval",
    ]
    report_hits = sum(1 for term in report_terms if term in lowered)

    # Check for news/article indicators
    news_terms = ["news", "article", "blog", "press release", "announced"]
    news_hits = sum(1 for term in news_terms if term in lowered)

    # Check for landing page indicators
    landing_terms = ["overview", "about this report", "download the report", "get the report"]
    landing_hits = sum(1 for term in landing_terms if term in lowered)

    # Decision logic
    if text_len > 5000 and report_hits >= 3:
        result["detected_source_kind"] = "html_report_body"
    elif pdf_links and text_len < 3000:
        result["detected_source_kind"] = "download_form_required"
    elif news_hits >= 2 and report_hits < 2:
        result["detected_source_kind"] = "html_news_article"
    elif text_len < 2000 and landing_hits >= 1:
        result["detected_source_kind"] = "html_landing_page"
    elif text_len < 2000 and pdf_links:
        result["detected_source_kind"] = "download_form_required"
    elif text_len < 2000:
        result["detected_source_kind"] = "html_landing_page"
    else:
        result["detected_source_kind"] = "html_report_body"

    return result


def recommend_action(source_kind: str, http_status: int, candidate_pdfs: list,
                     candidate_datasets: list) -> str:
    """Recommend next action based on classification."""
    if http_status in (401, 403):
        return "mark_paywalled"
    if http_status in (404, 500, 502, 503):
        return "mark_failed"
    if http_status >= 400:
        return "mark_failed"

    if source_kind == "direct_pdf":
        return "process_directly"
    if source_kind == "direct_xlsx_csv":
        return "create_child_dataset_source"
    if source_kind == "html_report_body":
        return "process_directly"
    if source_kind == "html_news_article":
        return "skip_news_article"
    if source_kind == "html_landing_page" and candidate_pdfs:
        return "create_child_pdf_source"
    if source_kind == "html_landing_page":
        return "browser_resolution_needed"
    if source_kind == "download_form_required" and candidate_pdfs:
        return "create_child_pdf_source"
    if source_kind == "download_form_required":
        return "manual_download_needed"
    if source_kind == "js_required":
        return "browser_resolution_needed"
    if source_kind == "paywalled_or_gated":
        return "mark_paywalled"
    if source_kind == "dead_or_403":
        return "mark_failed"

    return "browser_resolution_needed"


def audit_source(source_id: str, url: str, source_type: str, crawl_status: str,
                 raw_file_path: str, title: str) -> dict:
    """Audit a single source."""
    row = {
        "source_id": source_id,
        "original_url": url,
        "source_type": source_type,
        "title": title or "",
        "crawl_status": crawl_status,
        "http_status": "",
        "content_type": "",
        "detected_source_kind": "",
        "text_length": 0,
        "candidate_pdfs": "",
        "candidate_datasets": "",
        "candidate_apis": "",
        "recommended_next_action": "",
        "notes": "",
    }

    # If already processed with raw file, use existing data
    if raw_file_path and crawl_status == "parsed":
        raw_path = Path("/data/hermes") / raw_file_path
        if raw_path.exists():
            try:
                content = raw_path.read_text(errors="ignore")
                text_len = len(trafilatura.extract(content) or "")
                row["text_length"] = text_len
                row["http_status"] = 200
                row["content_type"] = "text/html" if raw_path.suffix == ".html" else "application/pdf"

                if source_type == "pdf":
                    row["detected_source_kind"] = "direct_pdf"
                    row["recommended_next_action"] = "process_directly"
                else:
                    classification = classify_content(content, url, row["content_type"])
                    row["detected_source_kind"] = classification["detected_source_kind"]
                    row["candidate_pdfs"] = "|".join(classification["candidate_pdfs"][:5])
                    row["candidate_datasets"] = "|".join(classification["candidate_datasets"][:3])
                    row["candidate_apis"] = "|".join(classification["candidate_apis"][:3])
                    row["recommended_next_action"] = recommend_action(
                        classification["detected_source_kind"], 200,
                        classification["candidate_pdfs"], classification["candidate_datasets"]
                    )
            except Exception as e:
                row["notes"] = f"Error reading raw file: {e}"
                row["detected_source_kind"] = "unknown"
                row["recommended_next_action"] = "browser_resolution_needed"
        else:
            row["notes"] = "Raw file not found"
            row["detected_source_kind"] = "unknown"
            row["recommended_next_action"] = "process_directly" if source_type == "pdf" else "browser_resolution_needed"
        return row

    # If paywalled
    if crawl_status == "private_or_paywalled":
        row["http_status"] = 403
        row["detected_source_kind"] = "paywalled_or_gated"
        row["recommended_next_action"] = "mark_paywalled"
        return row

    # URL-based classification first
    url_class = classify_url(url)
    if url_class in ("direct_pdf", "direct_xlsx_csv"):
        row["detected_source_kind"] = url_class
        if url_class == "direct_pdf":
            row["recommended_next_action"] = "process_directly"
        else:
            row["recommended_next_action"] = "create_child_dataset_source"
        # Still need to check HTTP status
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS) as client:
                resp = client.head(url)
                row["http_status"] = resp.status_code
                row["content_type"] = resp.headers.get("content-type", "").split(";")[0]
        except httpx.HTTPStatusError as e:
            row["http_status"] = e.response.status_code
            if e.response.status_code in (401, 403):
                row["detected_source_kind"] = "paywalled_or_gated"
                row["recommended_next_action"] = "mark_paywalled"
            elif e.response.status_code == 404:
                row["recommended_next_action"] = "mark_failed"
        except Exception as e:
            row["notes"] = f"HTTP error: {str(e)[:100]}"
            row["recommended_next_action"] = "mark_failed"
        return row

    # HTML source — fetch and classify
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS) as client:
            resp = client.get(url)
            row["http_status"] = resp.status_code
            row["content_type"] = resp.headers.get("content-type", "").split(";")[0]

            if resp.status_code in (401, 403):
                row["detected_source_kind"] = "paywalled_or_gated"
                row["recommended_next_action"] = "mark_paywalled"
                return row
            if resp.status_code >= 400:
                row["detected_source_kind"] = "dead_or_403"
                row["recommended_next_action"] = "mark_failed"
                return row

            content = resp.text
            classification = classify_content(content, url, row["content_type"])
            row["detected_source_kind"] = classification["detected_source_kind"]
            row["candidate_pdfs"] = "|".join(classification["candidate_pdfs"][:5])
            row["candidate_datasets"] = "|".join(classification["candidate_datasets"][:3])
            row["candidate_apis"] = "|".join(classification["candidate_apis"][:3])

            extracted = trafilatura.extract(content) or ""
            row["text_length"] = len(extracted)

            row["recommended_next_action"] = recommend_action(
                classification["detected_source_kind"], resp.status_code,
                classification["candidate_pdfs"], classification["candidate_datasets"]
            )

    except httpx.TimeoutException:
        row["notes"] = "Request timed out"
        row["detected_source_kind"] = "unknown"
        row["recommended_next_action"] = "browser_resolution_needed"
    except httpx.RequestError as e:
        row["notes"] = f"Request failed: {str(e)[:100]}"
        row["detected_source_kind"] = "dead_or_403"
        row["recommended_next_action"] = "mark_failed"
    except Exception as e:
        row["notes"] = f"Error: {str(e)[:100]}"
        row["detected_source_kind"] = "unknown"
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

    print(f"Auditing {len(sources)} sources...")
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
        "http_status", "content_type", "detected_source_kind", "text_length",
        "candidate_pdfs", "candidate_datasets", "candidate_apis",
        "recommended_next_action", "notes",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nAudit saved to: {OUTPUT_CSV}")

    # Print summary
    from collections import Counter
    kind_counts = Counter(r["detected_source_kind"] for r in rows)
    action_counts = Counter(r["recommended_next_action"] for r in rows)

    print("\n=== Detected Source Kinds ===")
    for kind, count in kind_counts.most_common():
        print(f"  {kind:30s} {count:4d}")

    print("\n=== Recommended Actions ===")
    for action, count in action_counts.most_common():
        print(f"  {action:30s} {count:4d}")

    # Show PDF candidates
    pdf_candidates = [r for r in rows if r["candidate_pdfs"]]
    print(f"\n=== Sources with PDF Candidates: {len(pdf_candidates)} ===")
    for r in pdf_candidates[:15]:
        pdfs = r["candidate_pdfs"].split("|")[:2]
        print(f"  {r['detected_source_kind']:25s} {r['original_url'][:50]}")
        for p in pdfs:
            print(f"    -> {p[:80]}")

    # Show dataset candidates
    ds_candidates = [r for r in rows if r["candidate_datasets"]]
    print(f"\n=== Sources with Dataset Candidates: {len(ds_candidates)} ===")
    for r in ds_candidates[:10]:
        datasets = r["candidate_datasets"].split("|")[:2]
        print(f"  {r['original_url'][:60]}")
        for d in datasets:
            print(f"    -> {d[:80]}")


if __name__ == "__main__":
    main()
