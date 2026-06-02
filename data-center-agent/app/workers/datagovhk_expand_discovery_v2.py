"""Expanded data.gov.hk Discovery Worker.

Comprehensive search across 33+ terms to find all innovation ecosystem datasets.
Builds on the initial discovery but with much broader coverage.

Usage:
  python -m app.workers.datagovhk_expand_discovery_v2
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Expanded search terms - covers IP, innovation, business, economy
SEARCH_TERMS = [
    # IP/Patent specific
    "patent", "trademark", "trade mark", "intellectual property", "IP",
    "copyright", "licensing", "design registration",
    # Innovation ecosystem
    "innovation", "startup", "venture", "incubat", "accelerator",
    "R&D", "research", "technology", "science",
    # Business/Enterprise
    "SME", "enterprise", "business registration", "company",
    "corporate", "commerce", "industry",
    # Economy/Labor
    "employment", "economy", "census", "statistics",
    # Funding
    "fund", "investment", "grant",
    # Digital
    "digital", "fintech", "biotech",
    # Broader
    "application", "registration",
]

CKAN_API = "https://data.gov.hk/en-data/api/3/action/package_search"
OUTPUT_DIR = Path("/data/hermes/diagnostics/connector_priority_eval")

# High-value providers for innovation ecosystem
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
    "financial services and the treasury bureau",
    "invest hong kong", "investhk",
    "hong kong trade development council", "hktdc",
    "corporate services and entertainment licensing office",
    "education bureau",
    "university grants committee", "ugc",
}

# Innovation relevance keywords
INNOVATION_KEYWORDS = {
    "innovation", "startup", "patent", "trademark", "intellectual property",
    "technology", "r&d", "research", "sme", "small business", "enterprise",
    "digital", "venture", "incubator", "accelerator", "fintech", "biotech",
    "registration", "license", "business", "employment", "workforce",
    "science", "design", "copyright", "licensing", "grant", "fund",
    "investment", "application", "census", "statistics", "economy",
    "industry", "commerce", "company", "corporate",
}


def search_datasets(term: str, rows: int = 50) -> list[dict[str, Any]]:
    """Query data.gov.hk CKAN API for a search term."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
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
    """Check if dataset has a direct CSV/XLSX/API download URL."""
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
    score += min(keyword_hits * 0.06, 0.4)

    # Search term in title (strong signal)
    if search_term.lower() in title:
        score += 0.2

    # Provider is high-value
    if any(hvp in provider for hvp in HIGH_VALUE_PROVIDERS):
        score += 0.2

    # Has resources
    num_resources = len(dataset.get("resources", []))
    if num_resources > 0:
        score += min(num_resources * 0.02, 0.1)

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
    csv_formats = [f for f in fmts if f in ("CSV", "XLSX", "XLS")]
    if csv_formats:
        score += 0.15
        reasons.append(f"Direct download: {', '.join(csv_formats)}")

    # API available
    if "API" in fmts:
        score += 0.1
        reasons.append("API endpoint available")

    # Provider
    provider = (dataset.get("organization", {}).get("title") or "").lower()
    matched_providers = [hvp for hvp in HIGH_VALUE_PROVIDERS if hvp in provider]
    if matched_providers:
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

    all_datasets: dict[str, dict] = {}
    by_term: dict[str, int] = {}

    for term in SEARCH_TERMS:
        results = search_datasets(term, rows=50)
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
        print(f"  '{term}': {term_count} new ({len(results)} returned)")

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

    candidates.sort(key=lambda x: x["sync_priority_score"], reverse=True)

    # Tier 1: High priority (score >= 0.5) with direct download
    tier1 = [c for c in candidates if c["sync_priority_score"] >= 0.5 and c["direct_download_url"]]

    # Tier 2: Medium priority (score >= 0.3) with direct download
    tier2 = [c for c in candidates if 0.3 <= c["sync_priority_score"] < 0.5 and c["direct_download_url"]]

    # Tier 3: Worth considering (score >= 0.4)
    tier3 = [c for c in candidates if c["sync_priority_score"] >= 0.4 and not c["direct_download_url"]]

    _write_all_candidates_csv(candidates)
    _write_top_candidates_csv(tier1, "datagovhk_tier1_sync_candidates.csv")
    _write_top_candidates_csv(tier2, "datagovhk_tier2_sync_candidates.csv")
    _write_top_candidates_csv(tier3, "datagovhk_tier3_candidates.csv")
    _write_summary_md(candidates, tier1, tier2, tier3, by_term)

    return {
        "total_unique": len(all_datasets),
        "by_term": by_term,
        "tier1": len(tier1),
        "tier2": len(tier2),
        "tier3": len(tier3),
        "output_dir": str(OUTPUT_DIR),
    }


def _write_all_candidates_csv(candidates: list[dict]) -> None:
    path = OUTPUT_DIR / "datagovhk_discovery_all_candidates.csv"
    fieldnames = ["dataset_id", "title", "provider", "notes", "num_resources",
                  "formats", "relevance_score", "sync_priority_score",
                  "direct_download_url", "search_term"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    print(f"  Wrote {len(candidates)} candidates to {path}")


def _write_top_candidates_csv(candidates: list[dict], filename: str) -> None:
    path = OUTPUT_DIR / filename
    fieldnames = ["dataset_id", "title", "provider", "formats",
                  "direct_download_url", "sync_priority_score", "reasons"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    print(f"  Wrote {len(candidates)} candidates to {path}")


def _write_summary_md(candidates: list[dict], tier1: list, tier2: list, tier3: list, by_term: dict) -> None:
    path = OUTPUT_DIR / "datagovhk_discovery_summary_v2.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# data.gov.hk Discovery Summary v2 (Expanded)\n\n")
        f.write(f"Generated: {now}\n\n")
        f.write(f"## Overview\n\n")
        f.write(f"- **Total unique datasets found**: {len(candidates)}\n")
        f.write(f"- **Search terms**: {len(by_term)}\n")
        f.write(f"- **Tier 1** (high priority, direct download): {len(tier1)}\n")
        f.write(f"- **Tier 2** (medium priority, direct download): {len(tier2)}\n")
        f.write(f"- **Tier 3** (worth considering): {len(tier3)}\n\n")

        f.write("## Tier 1: High Priority Sync Candidates\n\n")
        f.write("Direct CSV/XLSX downloads from official providers, high relevance.\n\n")
        f.write("| # | Title | Provider | Formats | Priority |\n")
        f.write("|---|-------|----------|---------|----------|\n")
        for i, c in enumerate(tier1[:30], 1):
            f.write(f"| {i} | {c['title'][:60]} | {c['provider'][:30]} | {c['formats']} | {c['sync_priority_score']:.2f} |\n")

        f.write(f"\n## Tier 2: Medium Priority\n\n")
        f.write("| # | Title | Provider | Formats | Priority |\n")
        f.write("|---|-------|----------|---------|----------|\n")
        for i, c in enumerate(tier2[:20], 1):
            f.write(f"| {i} | {c['title'][:60]} | {c['provider'][:30]} | {c['formats']} | {c['sync_priority_score']:.2f} |\n")

        f.write(f"\n## Tier 3: Worth Considering\n\n")
        for i, c in enumerate(tier3[:15], 1):
            f.write(f"{i}. **{c['title'][:70]}** ({c['provider'][:30]}) — {c['formats']} — {c['sync_priority_score']:.2f}\n")

        f.write(f"\n## Top Sync URLs (Tier 1)\n\n")
        f.write("Ready for immediate sync:\n\n")
        for i, c in enumerate(tier1[:20], 1):
            f.write(f"{i}. `{c['direct_download_url']}`\n")

    print(f"  Wrote summary to {path}")


def main() -> None:
    print("=" * 60)
    print("data.gov.hk Expanded Discovery v2")
    print("=" * 60)
    print(f"\nSearch terms: {len(SEARCH_TERMS)}")
    print(f"Output: {OUTPUT_DIR}\n")

    results = run_discovery()

    print(f"\n{'=' * 60}")
    print(f"Total unique: {results['total_unique']}")
    print(f"Tier 1 (high priority): {results['tier1']}")
    print(f"Tier 2 (medium priority): {results['tier2']}")
    print(f"Tier 3 (worth considering): {results['tier3']}")


if __name__ == "__main__":
    main()
