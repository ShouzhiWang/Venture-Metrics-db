#!/usr/bin/env python3
"""Variable quality audit: sample 100 variables and classify each.

Categories:
- good_codebook_variable: clear definition, proper source, reasonable name
- chart_metric: extracted from chart data (deal count, fund count, etc.)
- noise_artifact: chart labels, axis labels, source citations, fragments
- duplicate: same variable appearing multiple times
- unclear: ambiguous or partially extracted
"""

import json
import random
import re
from collections import Counter
from pathlib import Path
from uuid import UUID

from app.db.connection import get_engine
from app.agents.codebook_extractor import HybridCodebookExtractor
from sqlalchemy import text

OUTPUT_DIR = Path("/data/hermes/audits")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_JSON = OUTPUT_DIR / "variable_quality_audit.json"

# Chart/noise patterns
CHART_NOISE_PATTERNS = [
    r"^source$",
    r"^note[s]?$",
    r"^source:.*",
    r"^deal count",
    r"^fund count",
    r"^exit count",
    r"^b\)",
    r"^a\)",
    r"^c\)",
    r"^m\)",
    r"up.*flat.*down",
    r"series [a-h]\b",
    r"angel.*seed.*pre-seed",
    r"acquisition.*buyout.*public",
    r"first-time.*follow-on",
    r"^pre-seed/seed$",
    r"^early-stage$",
    r"^late-stage$",
    r"^growth$",
    r"^corporate$",
]

STRONG_DEFINITION_PATTERNS = [
    r"defined as",
    r"measured as",
    r"measured by",
    r"calculated as",
    r"proxy for",
    r"is a .* that",
    r"refers to",
    r"captures",
]


def classify_variable(var: dict) -> str:
    """Classify a single extracted variable."""
    name = (var.get("raw_variable_name") or "").strip()
    definition = var.get("definition") or ""
    measurement = var.get("measurement_method") or ""
    evidence = var.get("evidence_quote") or ""
    source_type = var.get("data_source_type") or ""
    availability = var.get("availability") or ""
    confidence = var.get("confidence_score") or 0

    name_lower = name.lower().strip()

    # Check for noise artifacts
    for pattern in CHART_NOISE_PATTERNS:
        if re.search(pattern, name_lower):
            # But if it also has a strong definition, it might be legitimate
            has_definition = bool(definition and len(definition) > 20)
            if not has_definition:
                return "noise_artifact"

    # Check for chart metrics (short name, no definition, from chart context)
    if not definition and not measurement:
        if len(name_lower) < 15 and confidence < 0.8:
            # Short name without definition — likely a chart metric
            chart_terms = ["count", "value", "amount", "total", "average", "median", "share"]
            if any(t in name_lower for t in chart_terms):
                return "chart_metric"

    # Check for strong definitions
    has_strong_def = False
    for pattern in STRONG_DEFINITION_PATTERNS:
        if re.search(pattern, definition.lower()):
            has_strong_def = True
            break

    if has_strong_def and len(definition) > 30:
        return "good_codebook_variable"

    if definition and len(definition) > 20:
        return "good_codebook_variable"

    if measurement and len(measurement) > 20:
        return "good_codebook_variable"

    # Check for duplicates (same name in evidence)
    # This is handled at the group level below

    # Partial or unclear
    if definition or measurement:
        return "unclear"

    # No definition at all — likely noise
    return "noise_artifact"


def main():
    # Load batch results
    batch_path = Path("/data/hermes/audits/batch_processing_results.json")
    with open(batch_path) as f:
        batch_results = json.load(f)

    # Get processed sources
    processed = [r for r in batch_results if r["status"] == "processed"]
    print(f"Processed sources: {len(processed)}")

    # Extract variables from each source
    all_variables = []
    engine = get_engine()

    for src in processed:
        report_id = src.get("report_id")
        if not report_id:
            continue

        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT rv.raw_variable_name, rv.definition, rv.measurement_method,
                           rv.data_source_text, rv.data_source_type, rv.availability,
                           rv.confidence_score, rv.evidence_quote, rv.review_status,
                           rv.report_id::text, rv.page_number
                    FROM report_variables rv
                    WHERE rv.report_id = :rid
                """), {"rid": report_id})
                for row in result.fetchall():
                    all_variables.append({
                        "raw_variable_name": row[0],
                        "definition": row[1],
                        "measurement_method": row[2],
                        "data_source_text": row[3],
                        "data_source_type": row[4],
                        "availability": row[5],
                        "confidence_score": row[6],
                        "evidence_quote": row[7],
                        "review_status": row[8],
                        "report_id": row[9],
                        "page_number": row[10],
                        "source_title": src.get("title", ""),
                    })
        except Exception as e:
            print(f"  Error querying report {report_id}: {e}")

    print(f"Total variables in DB: {len(all_variables)}")

    # These are from the batch run which was dry-run only — variables weren't inserted
    # Let me check if they're actually in the DB
    if len(all_variables) == 0:
        print("\nNo variables in DB (batch was dry-run). Re-extracting from chunks...")
        all_variables = reextract_variables(processed, engine)

    # Sample 100 (or all if fewer)
    sample_size = min(100, len(all_variables))
    if len(all_variables) > sample_size:
        random.seed(42)
        sample = random.sample(all_variables, sample_size)
    else:
        sample = all_variables

    print(f"Classifying {len(sample)} variables...")

    # Classify each
    classifications = []
    name_groups = {}
    for var in sample:
        cat = classify_variable(var)
        classifications.append({
            "category": cat,
            "raw_variable_name": var.get("raw_variable_name", ""),
            "definition": (var.get("definition") or "")[:100],
            "source_title": (var.get("source_title") or "")[:50],
            "confidence_score": var.get("confidence_score", 0),
            "availability": var.get("availability", ""),
            "report_id": var.get("report_id", ""),
        })

        # Track duplicates by normalized name
        name_key = re.sub(r"[^a-z0-9]", "", (var.get("raw_variable_name") or "").lower())
        if name_key not in name_groups:
            name_groups[name_key] = []
        name_groups[name_key].append(classifications[-1])

    # Mark duplicates
    for name_key, group in name_groups.items():
        if len(group) > 1:
            for item in group:
                if item["category"] == "good_codebook_variable":
                    item["category"] = "duplicate"
                    item["duplicate_of"] = group[0]["raw_variable_name"]

    # Summary
    cats = Counter(c["category"] for c in classifications)
    print("\n=== Variable Quality Classification ===")
    for cat, count in cats.most_common():
        pct = count / len(classifications) * 100
        print(f"  {cat:30s} {count:3d} ({pct:.1f}%)")

    # Show examples of each category
    for cat in ["good_codebook_variable", "chart_metric", "noise_artifact", "duplicate", "unclear"]:
        examples = [c for c in classifications if c["category"] == cat][:3]
        if examples:
            print(f"\n--- {cat} examples ---")
            for ex in examples:
                print(f"  name: {ex['raw_variable_name'][:50]}")
                print(f"  def:  {ex['definition'][:80]}")
                print(f"  src:  {ex['source_title']}")
                print()

    # Save
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "total_variables": len(all_variables),
            "sample_size": len(sample),
            "classifications": classifications,
            "summary": dict(cats),
        }, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nSaved to: {OUTPUT_JSON}")


def reextract_variables(processed, engine):
    """Re-extract variables from chunks for dry-run sources."""
    from app.agents.codebook_extractor import HybridCodebookExtractor

    all_vars = []
    extractor = HybridCodebookExtractor(top_k=40)

    for src in processed:
        report_id = src.get("report_id")
        if not report_id:
            continue

        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT chunk_text, page_number, section_title, chunk_type, id::text
                    FROM document_chunks
                    WHERE report_id = :rid
                    ORDER BY page_number, id
                """), {"rid": report_id})
                chunks = [dict(row._mapping) for row in result.fetchall()]

            if not chunks:
                continue

            variables = extractor.extract(UUID(report_id), chunks)
            for v in variables:
                all_vars.append({
                    "raw_variable_name": v.raw_variable_name,
                    "definition": v.definition,
                    "measurement_method": v.measurement_method,
                    "data_source_text": v.data_source_text,
                    "data_source_type": v.data_source_type,
                    "availability": v.availability,
                    "confidence_score": v.confidence_score,
                    "evidence_quote": v.evidence_quote,
                    "review_status": v.review_status,
                    "report_id": str(v.report_id),
                    "page_number": v.page_number,
                    "source_title": src.get("title", ""),
                })
        except Exception as e:
            print(f"  Error re-extracting from {report_id}: {e}")

    print(f"Re-extracted {len(all_vars)} variables from {len(processed)} sources")
    return all_vars


if __name__ == "__main__":
    main()
