"""Run focused HK eval queries against find_data and capture results."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from app.db.connection import get_engine
from app.workers.find_data import find_data

DIAGNOSTICS_DIR = Path("/data/hermes/diagnostics/connector_sync_eval")

QUERIES = [
    "Hong Kong innovation output",
    "Hong Kong patent data",
    "Hong Kong IP statistics",
    "Hong Kong startup organizations",
    "Hong Kong university TTOs",
    "Hong Kong startup incubators",
    "Hong Kong spin-off companies",
    "public datasets for Hong Kong innovation metrics",
]


def run_eval():
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for query in QUERIES:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}")

        result = find_data(query, limit=5)

        variables = result.get("closest_variables", [])
        connector_datasets = result.get("connector_datasets", [])
        organizations = result.get("relevant_organizations", [])
        connector_candidates = result.get("connector_candidates", [])
        reports = result.get("relevant_reports", [])
        sources = result.get("source_links", [])

        # Check if answer would mention cached/synced status
        has_synced = any(d.get("data_status") == "synced" for d in connector_datasets)
        has_metadata_only = any(d.get("data_status") == "metadata_only" for d in connector_datasets)
        has_org_metadata = any(o.get("data_status") == "organization_metadata" for o in organizations)
        mentions_status = has_synced or has_metadata_only or has_org_metadata

        # Score 0-5
        score = 0
        if variables:
            score += 1
        if connector_datasets:
            score += 1
        if organizations:
            score += 1
        if connector_candidates:
            score += 0.5
        if reports:
            score += 0.5
        if has_synced:
            score += 0.5
        if mentions_status:
            score += 0.5
        score = min(5, score)

        # Remaining missing data
        missing = []
        if not variables:
            missing.append("No structured variables found")
        if not connector_datasets and not connector_candidates:
            missing.append("No connector datasets or candidates")
        if not organizations:
            missing.append("No HK organizations found")
        if has_metadata_only and not has_synced:
            missing.append("Connector data is metadata-only, not synced")

        entry = {
            "query": query,
            "variables_count": len(variables),
            "connector_datasets_count": len(connector_datasets),
            "organizations_count": len(organizations),
            "connector_candidates_count": len(connector_candidates),
            "reports_count": len(reports),
            "sources_count": len(sources),
            "mentions_status": mentions_status,
            "has_synced": has_synced,
            "has_metadata_only": has_metadata_only,
            "has_org_metadata": has_org_metadata,
            "score": score,
            "missing": "; ".join(missing) if missing else "None",
            "top_variables": "; ".join(v.get("title", "")[:50] for v in variables[:3]),
            "top_connector_datasets": "; ".join(d.get("title", "")[:50] for d in connector_datasets[:3]),
            "top_organizations": "; ".join(o.get("title", "")[:50] for o in organizations[:3]),
        }
        results.append(entry)

        # Print summary
        print(f"  Variables: {len(variables)}")
        print(f"  Connector datasets: {len(connector_datasets)}")
        print(f"  Organizations: {len(organizations)}")
        print(f"  Connector candidates: {len(connector_candidates)}")
        print(f"  Reports: {len(reports)}")
        print(f"  Score: {score}/5")
        if connector_datasets:
            for d in connector_datasets[:2]:
                print(f"    DS: {d.get('title')} [{d.get('data_status')}]")
        if organizations:
            for o in organizations[:3]:
                print(f"    Org: {o.get('title')} ({o.get('organization_type')})")
        if missing:
            print(f"  Missing: {'; '.join(missing)}")

    # Write CSV
    csv_path = DIAGNOSTICS_DIR / "hk_focused_eval.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    # Write summary markdown
    md_path = DIAGNOSTICS_DIR / "connector_sync_summary.md"
    # Read existing summary and append eval section
    existing = ""
    if md_path.exists():
        existing = md_path.read_text(encoding="utf-8")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(existing)
        if not existing:
            f.write("# Connector Sync & Eval Summary\n\n")
            f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")

        f.write("\n## 4. Focused HK Eval Queries\n\n")
        f.write(f"Total queries: {len(results)}\n\n")
        avg_score = sum(r["score"] for r in results) / len(results)
        f.write(f"**Average score: {avg_score:.1f}/5**\n\n")

        f.write("| Query | Variables | Conn Datasets | Orgs | Candidates | Score | Status Mentions |\n")
        f.write("|-------|-----------|---------------|------|------------|-------|-----------------|\n")
        for r in results:
            status_parts = []
            if r["has_synced"]:
                status_parts.append("synced")
            if r["has_metadata_only"]:
                status_parts.append("metadata-only")
            if r["has_org_metadata"]:
                status_parts.append("org-metadata")
            f.write(f"| {r['query'][:35]} | {r['variables_count']} | {r['connector_datasets_count']} | "
                    f"{r['organizations_count']} | {r['connector_candidates_count']} | "
                    f"{r['score']:.1f} | {', '.join(status_parts) or 'none'} |\n")

        f.write("\n### Remaining Gaps\n\n")
        all_missing = set()
        for r in results:
            if r["missing"] != "None":
                for m in r["missing"].split("; "):
                    all_missing.add(m)
        for m in sorted(all_missing):
            f.write(f"- {m}\n")

    print(f"\n\nResults written to:")
    print(f"  {csv_path}")
    print(f"  {md_path}")
    print(f"\nAverage score: {avg_score:.1f}/5")


if __name__ == "__main__":
    run_eval()
