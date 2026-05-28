from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import mean
from typing import Any

from app.services.research_task import execute_research_task


NORMAL_QUERIES = [
    "Singapore startup funding by stage",
    "Hong Kong innovation output",
    "public data on business births",
]
CLARIFICATION_QUERIES = [
    "startup data",
    "innovation ecosystem in Asia",
    "funding trends",
    "make me a dataset on Asian startups",
    "analyze Singapore startups",
]
EXPORT_QUERIES = [
    "Create an Excel of Singapore startup funding by stage",
    "Build a table of Singapore startup funding by year",
]
COMPARABILITY_QUERIES = [
    "Sum startup funding values across all Singapore reports",
    "Aggregate VC investment across Singapore and Southeast Asia",
]


def fixture_results(query: str) -> dict[str, Any]:
    variables = [
        {
            "object_id": "var-funding-stage",
            "title": "Singapore startup funding by stage",
            "score": 0.88,
            "definition": "Startup funding amount split by investment stage.",
            "measurement_method": "Reported funding amount by stage.",
            "value": 42.5,
            "unit": "USD million",
            "availability": "obtainable",
            "temporal_coverage": "2023",
            "geographic_coverage": "Singapore",
            "source_url": "https://example.org/venture-report",
            "evidence_quote": "Seed funding reached 42.5 USD million in 2023.",
            "data_source": "Singapore Venture Report",
        },
        {
            "object_id": "var-funding-stage-private",
            "title": "Singapore startup deal count by stage",
            "score": 0.71,
            "definition": "Number of startup deals split by investment stage.",
            "measurement_method": "Count of announced funding rounds by stage.",
            "value": 120,
            "unit": "deals",
            "availability": "private",
            "temporal_coverage": "2022",
            "geographic_coverage": "Singapore",
            "source_url": "https://example.org/venture-report",
            "evidence_quote": "Seed stage had 120 deals in 2022.",
            "data_source": "Singapore Venture Report",
        },
    ]
    if "business births" in query.lower():
        variables = [
            {
                "object_id": "var-business-births",
                "title": "Business births",
                "score": 0.8,
                "definition": "New business registrations or employer enterprise births.",
                "unit": "count",
                "availability": "obtainable",
                "temporal_coverage": "2023",
                "geographic_coverage": "Singapore",
                "source_url": "https://example.org/statistics",
                "evidence_quote": "The source reports 8,500 business births in 2023.",
                "data_source": "Official Statistics",
            }
        ]
    return {
        "closest_variables": variables,
        "relevant_reports": [
            {
                "object_id": "report-1",
                "title": "Singapore Venture Report",
                "publisher": "Example Publisher",
                "geography": "Singapore",
                "report_year": 2024,
                "source_url": "https://example.org/venture-report",
                "score": 0.9,
            }
        ],
        "source_links": [
            {"title": "Singapore Venture Report", "source_url": "https://example.org/venture-report", "availability": "obtainable"}
        ],
        "relevant_organizations": [],
    }


def fake_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": fixture_results(str(args.get("query") or ""))}


def evaluate(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = output_dir / "generated_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    answer_rows = []
    clarification_rows = []
    export_rows = []
    comparability_rows = []
    artifact_rows = []

    for query in NORMAL_QUERIES:
        result = execute_research_task(query, tool_caller=fake_tool, output_dir=artifacts_dir, use_llm=False)
        answer = result.get("answer", "")
        score = score_answer(result)
        answer_rows.append({"query_group": "normal_synthesis", "query": query, "score": score, "answer_preview": answer[:240]})

    for query in CLARIFICATION_QUERIES:
        result = execute_research_task(query, tool_caller=fake_tool, output_dir=artifacts_dir, use_llm=False)
        questions = result.get("clarifying_questions") or []
        score = 5 if result.get("type") == "clarification" and questions and questions[0].get("options") else 1
        clarification_rows.append(
            {
                "query_group": "clarification",
                "query": query,
                "score": score,
                "returned_clarification": result.get("type") == "clarification",
                "questions": " | ".join(item.get("question", "") for item in questions),
            }
        )

    for query in EXPORT_QUERIES:
        fmt = "xlsx" if "excel" in query.lower() else "csv"
        result = execute_research_task(query, tool_caller=fake_tool, output_dir=artifacts_dir, output_format=fmt, use_llm=False)
        export = result.get("export") or {}
        score = 5 if export.get("path") and result.get("normalized_data") else 2
        export_rows.append({"query_group": "export", "query": query, "score": score, "format": export.get("format"), "path": export.get("path")})
        if export.get("path"):
            artifact_rows.append({"query_group": "export", "query": query, "artifact_type": export.get("format"), "path": export.get("path")})

    for query in COMPARABILITY_QUERIES:
        result = execute_research_task(query, tool_caller=fake_tool, output_dir=artifacts_dir, output_format="csv", use_llm=False)
        comp = result.get("comparability") or {}
        score = 5 if comp.get("status") == "not_comparable" and comp.get("explanation") and comp.get("comparison_table") else 2
        comparability_rows.append(
            {
                "query_group": "comparability",
                "query": query,
                "score": score,
                "status": comp.get("status"),
                "can_aggregate": comp.get("can_aggregate"),
                "explanation": comp.get("explanation"),
            }
        )

    paths = {
        "answer_quality_eval": output_dir / "answer_quality_eval.csv",
        "clarification_eval": output_dir / "clarification_eval.csv",
        "export_task_eval": output_dir / "export_task_eval.csv",
        "comparability_eval": output_dir / "comparability_eval.csv",
        "generated_artifacts_index": output_dir / "generated_artifacts_index.csv",
        "summary": output_dir / "research_task_fix_eval_summary.md",
    }
    write_csv(paths["answer_quality_eval"], answer_rows)
    write_csv(paths["clarification_eval"], clarification_rows)
    write_csv(paths["export_task_eval"], export_rows)
    write_csv(paths["comparability_eval"], comparability_rows)
    write_csv(paths["generated_artifacts_index"], artifact_rows)
    write_summary(paths["summary"], answer_rows, clarification_rows, export_rows, comparability_rows)
    return paths


def score_answer(result: dict[str, Any]) -> int:
    answer = result.get("answer", "")
    packet = result.get("evidence_packet") or {}
    score = 1
    if answer.startswith("Direct answer:"):
        score += 1
    if "Direct matches:" in answer or "Contextual matches:" in answer:
        score += 1
    if packet.get("availability_labels"):
        score += 1
    if any(item.get("value") is not None for item in packet.get("variables") or []):
        score += 1
    return min(score, 5)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, *groups: list[dict[str, Any]]) -> None:
    lines = ["# Research Task Fix Evaluation Summary", ""]
    names = ["Normal synthesis", "Clarification", "Export", "Comparability"]
    for name, rows in zip(names, groups, strict=True):
        scores = [float(row["score"]) for row in rows]
        lines.append(f"- {name}: {mean(scores):.2f}/5 across {len(rows)} queries")
    all_scores = [float(row["score"]) for rows in groups for row in rows]
    lines.extend(["", f"Overall: {mean(all_scores):.2f}/5", "", "Notes: evaluation uses existing research-task logic with fixture tool results; no ingestion, extraction batches, schema changes, or LLM/API calls were used."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate research task execution layer fixes.")
    parser.add_argument("--output-dir", default="diagnostics_research_task_fix")
    args = parser.parse_args()
    paths = evaluate(Path(args.output_dir))
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
