"""Table Analyzer — LLM-driven column mapping + Python computation.

Given a table_packet from source_reader and a user query, this module:
1. Uses LLM to identify which columns map to the query dimensions
2. Uses Python (pandas) to filter, aggregate, and compute actual values
3. Returns a structured analysis result with computed data

The LLM never does arithmetic — it only identifies columns and filters.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def analyze_table_for_query(
    query: str,
    table_packet: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """Analyze a table packet against a user query.

    Returns:
    {
        "can_answer": bool,
        "answer_confidence": "high" | "medium" | "low",
        "column_mapping": { ... },
        "computed_results": { ... },
        "data_quality_notes": [ ... ],
        "evidence_level": "table_values_read" | "metadata_only",
    }
    """
    if table_packet.get("packet_type") != "table":
        return {
            "can_answer": False,
            "answer_confidence": "none",
            "column_mapping": {},
            "computed_results": {},
            "data_quality_notes": ["Source is not a table — cannot compute values."],
            "evidence_level": "metadata_only",
        }

    columns = table_packet.get("columns") or []
    rows_sample = table_packet.get("rows_sample") or []
    if not columns or not rows_sample:
        return {
            "can_answer": False,
            "answer_confidence": "none",
            "column_mapping": {},
            "computed_results": {},
            "data_quality_notes": ["Table has no columns or rows."],
            "evidence_level": "metadata_only",
        }

    # Step 1: LLM column mapping
    column_mapping = _llm_column_mapping(query, columns, rows_sample, llm_client=llm_client)

    # Step 2: Python computation
    computed = _compute_from_mapping(query, table_packet, column_mapping)

    # Step 3: Determine if this can answer the query
    # Require actual computed values (aggregations or time_series), not just filtered rows
    has_computed_values = bool(computed.get("aggregations") or computed.get("time_series") or computed.get("geo_breakdown"))
    can_answer = has_computed_values and bool(column_mapping.get("metric_columns"))
    confidence = "high" if computed.get("aggregations") and computed.get("time_series") else \
                 "medium" if computed.get("aggregations") else "low"

    return {
        "can_answer": can_answer,
        "answer_confidence": confidence,
        "column_mapping": column_mapping,
        "computed_results": computed,
        "data_quality_notes": computed.get("data_quality_notes", []),
        "evidence_level": "table_values_read" if can_answer else "metadata_only",
        "source_title": table_packet.get("title"),
        "source_url": table_packet.get("source_url"),
        "retrieved_at": table_packet.get("retrieved_at"),
    }


# ---------------------------------------------------------------------------
# LLM column mapping
# ---------------------------------------------------------------------------

def _llm_column_mapping(
    query: str,
    columns: list[dict],
    rows_sample: list[dict],
    *,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """Ask the LLM to identify which columns map to query dimensions."""
    col_summary = []
    for col in columns:
        samples = col.get("sample_values", [])
        col_summary.append(f"- {col['name']} (dtype={col['dtype']}, samples={samples[:3]})")

    rows_preview = json.dumps(rows_sample[:5], ensure_ascii=True, default=str)

    prompt = f"""You are analyzing a data table to answer a user query.

User query: {query}

Table columns:
{chr(10).join(col_summary)}

First 5 rows:
{rows_preview}

Identify which columns map to these dimensions. Return one JSON object:

{{
  "time_column": "column name for year/date/time (or null)",
  "geography_column": "column name for country/region/city (or null)",
  "metric_columns": ["column names that contain numeric values relevant to the query"],
  "dimension_columns": ["column names for categories/sectors/stages etc."],
  "filters": {{
    "column_name": "specific value to filter on"
  }},
  "relevance": "direct | partial | irrelevant",
  "relevance_reason": "why this table is or isn't relevant to the query"
}}

Rules:
- Only include columns that actually exist in the table.
- metric_columns must be numeric (int/float) columns that measure something relevant.
- If the table cannot answer the query at all, set relevance to "irrelevant".
- Do not invent column names.
"""

    try:
        if llm_client and hasattr(llm_client, "plan"):
            # Use the LLM's JSON completion
            result = llm_client._json_completion(prompt) if hasattr(llm_client, "_json_completion") else {}
        elif llm_client:
            # Try calling as a simple completion
            from app.agents.demo_llm import DemoLLMClient
            if isinstance(llm_client, DemoLLMClient):
                result = llm_client._json_completion(prompt)
            else:
                result = {}
        else:
            result = _heuristic_column_mapping(query, columns, rows_sample)
    except Exception as exc:
        logger.debug("LLM column mapping failed, using heuristic: %s", exc)
        result = _heuristic_column_mapping(query, columns, rows_sample)

    return result


def _heuristic_column_mapping(
    query: str,
    columns: list[dict],
    rows_sample: list[dict],
) -> dict[str, Any]:
    """Fallback heuristic column mapping when LLM is unavailable."""
    lowered = query.lower()
    time_col = None
    geo_col = None
    metric_cols = []
    dim_cols = []
    filters = {}

    time_keywords = {"year", "date", "time", "period", "month", "quarter"}
    geo_keywords = {"country", "region", "city", "geography", "location", "area", "state", "province"}
    skip_keywords = {"id", "index", "code", "iso", "flag", "note", "source", "url", "link"}

    for col in columns:
        name_lower = col["name"].lower()
        dtype = col.get("dtype", "")

        if any(kw in name_lower for kw in time_keywords):
            time_col = col["name"]
        elif any(kw in name_lower for kw in geo_keywords):
            geo_col = col["name"]
        elif any(kw in name_lower for kw in skip_keywords):
            continue
        elif "int" in dtype or "float" in dtype:
            metric_cols.append(col["name"])
        elif col.get("non_null_count", 0) > 0:
            # Check if it looks categorical (few unique values)
            samples = col.get("sample_values", [])
            if len(set(samples)) <= 10:
                dim_cols.append(col["name"])

    return {
        "time_column": time_col,
        "geography_column": geo_col,
        "metric_columns": metric_cols[:5],
        "dimension_columns": dim_cols[:3],
        "filters": filters,
        "relevance": "partial" if metric_cols else "irrelevant",
        "relevance_reason": "Heuristic column detection" + (" — found numeric metrics" if metric_cols else " — no numeric columns found"),
    }


# ---------------------------------------------------------------------------
# Python computation — the LLM never does arithmetic
# ---------------------------------------------------------------------------

def _compute_from_mapping(
    query: str,
    table_packet: dict[str, Any],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    """Use Python/pandas to filter and compute values from the column mapping."""
    import pandas as pd

    rows = table_packet.get("rows_sample") or table_packet.get("full_rows") or []
    if not rows:
        return {"data_quality_notes": ["No rows available to compute."]}

    try:
        df = pd.DataFrame(rows)
    except Exception as exc:
        return {"data_quality_notes": [f"Could not build DataFrame: {exc}"]}

    result: dict[str, Any] = {"data_quality_notes": []}
    notes = result["data_quality_notes"]

    time_col = mapping.get("time_column")
    geo_col = mapping.get("geography_column")
    metric_cols = mapping.get("metric_columns") or []
    filters = mapping.get("filters") or {}

    # Apply filters
    for col_name, filter_value in filters.items():
        if col_name in df.columns:
            df = df[df[col_name].astype(str).str.lower() == str(filter_value).lower()]

    if df.empty:
        notes.append("No rows remain after applying filters.")
        return result

    # Coerce metric columns to numeric
    for col_name in metric_cols:
        if col_name in df.columns:
            df[col_name] = pd.to_numeric(df[col_name].astype(str).str.replace(",", "").str.strip(), errors="coerce")

    # Filtered rows
    result["filtered_rows"] = df.head(50).to_dict(orient="records")
    result["filtered_row_count"] = len(df)

    # Aggregations
    aggregations: dict[str, Any] = {}
    for col_name in metric_cols:
        if col_name in df.columns:
            series = df[col_name].dropna()
            if not series.empty:
                aggregations[col_name] = {
                    "count": int(series.count()),
                    "sum": round(float(series.sum()), 2),
                    "mean": round(float(series.mean()), 2),
                    "min": round(float(series.min()), 2),
                    "max": round(float(series.max()), 2),
                }

    if aggregations:
        result["aggregations"] = aggregations

    # Time series if time column exists
    if time_col and time_col in df.columns and metric_cols:
        try:
            df[time_col] = df[time_col].astype(str).str.strip()
            time_series = {}
            for col_name in metric_cols:
                if col_name in df.columns:
                    grouped = df.groupby(time_col)[col_name].agg(["mean", "sum", "count"]).dropna(how="all")
                    if not grouped.empty:
                        time_series[col_name] = {
                            str(k): {"mean": round(float(v["mean"]), 2) if pd.notna(v["mean"]) else None,
                                     "sum": round(float(v["sum"]), 2) if pd.notna(v["sum"]) else None,
                                     "count": int(v["count"]) if pd.notna(v["count"]) else None}
                            for k, v in grouped.iterrows()
                        }
            if time_series:
                result["time_series"] = time_series
        except Exception as exc:
            notes.append(f"Time series computation failed: {exc}")

    # Geography breakdown if geo column exists
    if geo_col and geo_col in df.columns and metric_cols:
        try:
            geo_breakdown = {}
            for col_name in metric_cols:
                if col_name in df.columns:
                    grouped = df.groupby(geo_col)[col_name].agg(["mean", "sum", "count"]).dropna(how="all")
                    if not grouped.empty:
                        geo_breakdown[col_name] = {
                            str(k): {"mean": round(float(v["mean"]), 2) if pd.notna(v["mean"]) else None,
                                     "sum": round(float(v["sum"]), 2) if pd.notna(v["sum"]) else None}
                            for k, v in grouped.head(20).iterrows()
                        }
            if geo_breakdown:
                result["geo_breakdown"] = geo_breakdown
        except Exception as exc:
            notes.append(f"Geography breakdown failed: {exc}")

    return result
