"""Controlled data.gov.hk Expansion Discovery Worker.

Searches the data.gov.hk CKAN API for innovation ecosystem datasets,
ranks them by sync priority, and outputs diagnostic files.

Usage:
  python -m app.workers.datagovhk_expand_discovery
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SEARCH_TERMS = [
    "innovation", "startup", "SME", "business registration",
    "patent", "trademark", "R&D", "technology", "employment",
    "digital economy", "enterprise",
]

CKAN_API = "https://data.gov.hk/en-data/api/3/action/package_search"
OUTPUT_DIR = Path("/data/hermes/diagnostics/connector_priority_eval")

# Innovation ecosystem relevance keywords
INNOVATION_KEYWORDS = {
    "innovation", "startup", "patent", "trademark", "intellectual property",
    "technology", "R&D", "research", "SME", "small business", "enterprise",
    "digital", "venture", "incubator", "accelerator", "fintech", "biotech",
    "registration", "license", "business", "employment", "workforce",
}

HIGH_VALUE_PROVIDERS = {
    "intellectual property department", "ipd",
    "census and statistics department",
    "innovation and technology commission", "itc",
    "innovation and technology fund", "itf",
    "trade and industry department",
    "companies registry",
    "office of the government chief information officer", "ogcio",
    "hong kong science and technology parks", "hkstp",
    "cyberport",
    "corporate services and entertainment licensing office",
}


def search_datasets(term: str, rows: int = 20) -> list[dict[str, Any]]:
    """Query data.gov.hk CKAN API for a search term."""
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(CKAN_API, params={"q": term, "rows": rows})
            resp.raise_for_status()
            data = resp.json()
            if data.get("success"):
                return data.get("result", {}).get("results", [])
    except Exception as exc:
        logger.warning("API error for term '%s': %s", term, exc)
    return []


def extract_formats(dataset: dict) -> list[str]:
    """Extract resource formats from a dataset."""
    formats = set()
    for res in dataset.get("resources", []):
        fmt = str(res.get("format", "")).upper().strip()
        if fmt:
            formats.add(fmt)
    return sorted(formats)


def has_direct_download(dataset: dict) -> str | None:
    """Check if dataset has a direct CSV/XLSX download URL."""
    for res in dataset.get("resources", []):
        fmt = str(res.get("format", "")).upper().strip()
        url = res.get("url", "")
        if fmt in ("CSV", "XLSX", "XLS") and url:
            return url
        if fmt == "API" and url:
            return url
    return None


def compute_relevance_score(dataset: dict, search_term: str) -> float:
    """Compute relevance score (0-1) for innovation ecosystem."""
    score = 0.0
    title = (dataset.get("title") or "").lower()
    notes = (dataset.get("notes") or "").lower()
    provider = (dataset.get("organization", {}).get("title") or "").lower()
    combined = f"{title} {notes} {provider}"

    # Keyword matches
    keyword_hits = sum(1 for kw in INNOVATION_KEYWORDS if kw.lower() in combined)
    score += min(keyword_hits * 0.08, 0.4)

    # Search term in title (strong signal)
    if search_term.lower() in title:
        score += 0.2

    # Provider is high-value
    if any(hvp in provider for hvp in HIGH_VALUE_PROVIDERS):
        score += 0.2

    # Has resources
    num_resources = len(dataset.get("resources", []))
    if num_resources > 0:
        score += min(num_resources * 0.03, 0.1)

    # Has direct download
    if has_direct_download(dataset):
        score += 0.1

    return min(score, 1.0)


def compute_sync_priority(dataset: dict, relevance_score: float) -> tuple[float, list[str]]:
    """Compute sync priority score and reasons."""
    score = relevance_score
    reasons = []

    fmts = extract_formats(dataset)
    direct_url = has_direct_download(dataset)

    # Direct CSV/XLSX available
    if any(f in fmts for f in ("CSV", "XLSX", "XLS")):
        score += 0.15
        reasons.append(f"Direct download: {', '.join(f for f in fmts if f in ('CSV', 'XLSX', 'XLS'))}")

    # API available
    if "API" in fmts:
        score += 0.1
        reasons.append("API endpoint available")

    # Provider
    provider = (dataset.get("organization", {}).get("title") or "").lower()
    if any(hvp in provider for hvp in HIGH_VALUE_PROVIDERS):
        score += 0.15
        reasons.append(f"Official provider: {dataset.get('organization', {}).get('title', '')}")

    # Resource clarity
    resources = dataset.get("resources", [])
    clear_resources = [r for r in resources if r.get("format") and r.get("url")]
    if len(clear_resources) >= 2:
        score += 0.05
        reasons.append(f"{len(clear_resources)} clear resources")

    return min(score, 1.0), reasons


def run_discovery() -> dict[str, Any]:
    """Run discovery across all search terms."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_datasets: dict[str, dict] = {}  # keyed by dataset id
    by_term: dict[str, int] = {}

    for term in SEARCH_TERMS:
        results = search_datasets(term, rows=20)
        term_count = 0
        for ds in results:
            ds_id = ds.get("id")
            if not ds_id:
                continue
            if ds_id not in all_datasets:
                relevance = compute_relevance_score(ds, term)
                all_datasets[ds_id] = {
                    "dataset": ds,
                    "search_term": term,
                    "relevance_score": relevance,
                }
                term_count += 1
        by_term[term] = term_count
        print(f"  '{term}': {term_count} new datasets ({len(results)} returned)")

    # Compute sync priority
    candidates = []
    for ds_id, info in all_datasets.items():
        ds = info["dataset"]
        relevance = info["relevance_score"]
        sync_score, reasons = compute_sync_priority(ds, relevance)
        direct_url = has_direct_download(ds)
        candidates.append({
            "dataset_id": ds_id,
            "title": ds.get("title", ""),
            "provider": ds.get("organization", {}).get("title", ""),
            "notes": (ds.get("notes") or "")[:200],
            "num_resources": len(ds.get("resources", [])),
            "formats": ", ".join(extract_formats(ds)),
            "relevance_score": round(relevance, 3),
            "sync_priority_score": round(sync_score, 3),
            "direct_download_url": direct_url or "",
            "search_term": info["search_term"],
            "reasons": "; ".join(reasons),
        })

    # Sort by sync priority
    candidates.sort(key=lambda x: x["sync_priority_score"], reverse=True)
    top_candidates = [c for c in candidates if c["sync_priority_score"] >= 0.3][:15]

    # Write outputs
    _write_all_candidates_csv(candidates)
    _write_top_candidates_csv(top_candidates)
    _write_summary_md(candidates, top_candidates, by_term)

    return {
        "total_unique": len(all_datasets),
        "by_term": by_term,
        "top_candidates": len(top_candidates),
        "output_dir": str(OUTPUT_DIR),
    }


def _write_all_candidates_csv(candidates: list[dict]) -> None:
    path = OUTPUT_DIR / "datagovhk_discovery_candidates.csv"
    fieldnames = ["dataset_id", "title", "provider", "notes", "num_resources",
                  "formats", "relevance_score", "sync_priority_score",
                  "direct_download_url", "search_term"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    print(f"  Wrote {len(candidates)} candidates to {path}")


def _write_top_candidates_csv(candidates: list[dict]) -> None:
    path = OUTPUT_DIR / "datagovhk_top_sync_candidates.csv"
    fieldnames = ["dataset_id", "title", "provider", "formats",
                  "direct_download_url", "sync_priority_score", "reasons"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    print(f"  Wrote {len(candidates)} top candidates to {path}")


def _write_summary_md(candidates: list[dict], top: list[dict], by_term: dict[str, int]) -> None:
    path = OUTPUT_DIR / "datagovhk_discovery_summary.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# data.gov.hk Discovery Summary\n\n")
        f.write(f"Generated: {now}\n\n")
        f.write(f"## Overview\n\n")
        f.write(f"- **Total unique datasets found**: {len(candidates)}\n")
        f.write(f"- **Search terms**: {len(by_term)}\n")
        f.write(f"- **Top sync candidates** (score ≥ 0.3): {len(top)}\n\n")

        f.write("## Results by Search Term\n\n")
        for term, count in sorted(by_term.items(), key=lambda x: -x[1]):
            f.write(f"- **{term}**: {count} new datasets\n")

        f.write(f"\n## Top Sync Candidates\n\n")
        f.write("| # | Title | Provider | Formats | Priority | Reason |\n")
        f.write("|---|-------|----------|---------|----------|--------|\n")
        for i, c in enumerate(top, 1):
            f.write(f"| {i} | {c['title'][:50]} | {c['provider'][:30]} | {c['formats']} | {c['sync_priority_score']:.2f} | {c['reasons'][:60]} |\n")

        f.write(f"\n## Recommended Sync Order\n\n")
        f.write("Based on priority score, official provider status, and direct data availability:\n\n")
        for i, c in enumerate(top[:10], 1):
            f.write(f"{i}. **{c['title']}** ({c['provider']}) — {c['formats']} — priority {c['sync_priority_score']:.2f}\n")
            if c['direct_download_url']:
                f.write(f"   - Direct URL: {c['direct_download_url']}\n")

        f.write(f"\n## Notes\n\n")
        f.write("- Discovery only — no data synced\n")
        f.write("- Candidates ranked by: official provider match, direct CSV/XLSX availability, innovation relevance, resource clarity\n")
        f.write("- Do NOT sync more than 10 top candidates without approval\n")

    print(f"  Wrote summary to {path}")


def main() -> None:
    print("=" * 60)
    print("data.gov.hk Expansion Discovery")
    print("=" * 60)
    print(f"\nSearch terms: {', '.join(SEARCH_TERMS)}")
    print(f"Output: {OUTPUT_DIR}\n")

    results = run_discovery()

    print(f"\nDone. {results['total_unique']} unique datasets found.")
    print(f"Top candidates: {results['top_candidates']}")


if __name__ == "__main__":
    main()
