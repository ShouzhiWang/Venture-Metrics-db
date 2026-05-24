from __future__ import annotations

import argparse
import json

from app.db.connection import get_demo_read_engine
from app.services.compare_concepts_auto import compare_concepts_auto
from app.utils.logging import configure_logging


def run_compare_concepts_auto(
    query: str,
    *,
    limit_reports: int = 5,
    limit_variables: int = 20,
    geography: str | None = None,
    public_only: bool = False,
    min_confidence: float | None = None,
) -> dict:
    engine = get_demo_read_engine()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            except Exception:
                pass
            return compare_concepts_auto(
                query,
                connection=connection,
                limit_reports=limit_reports,
                limit_variables=limit_variables,
                geography=geography,
                public_only=public_only,
                min_confidence=min_confidence,
            )
        finally:
            transaction.rollback()


def format_human(result: dict, *, debug: bool = False) -> str:
    lines = [f"Query: {result['query']}", "", "Auto-selected reports:"]
    if result.get("selected_reports"):
        for index, report in enumerate(result["selected_reports"], start=1):
            lines.append(f"{index}. {report.get('title') or report.get('report_id')}")
            matched = ", ".join(
                variable.get("raw_variable_name") or str(variable.get("variable_id"))
                for variable in report.get("matched_variables", [])[:5]
            )
            lines.append(f"   - matched variables: {matched or 'none'}")
            if debug:
                lines.append(f"   - score: {report.get('score')}")
                lines.append(f"   - report_id: {report.get('report_id')}")
    else:
        lines.append("No reports selected.")

    comparison = result.get("comparison") or {}
    lines.extend(["", "Comparison summary:", f"- {comparison.get('summary') or 'No comparison available.'}"])
    differences = comparison.get("definition_differences") or []
    if differences:
        lines.append("- Main differences:")
        for index, item in enumerate(differences[:5], start=1):
            label = item.get("raw_variable_name") or item.get("variable_id") or "Variable"
            definition = item.get("definition") or "No definition available"
            lines.append(f"  {index}. {label}: {definition}")
    lines.append(f"- Comparability: {comparison.get('comparability', 'unknown')}")

    if result.get("limitations"):
        lines.extend(["", "Limitations:"])
        for limitation in result["limitations"]:
            lines.append(f"- {limitation}")
    if result.get("clarifying_questions"):
        lines.extend(["", "Clarifying question:", result["clarifying_questions"][0]])
    if debug:
        lines.extend(["", "Debug metadata:", json.dumps(result.get("metadata", {}), default=str, ensure_ascii=True, indent=2)])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatically compare concept definitions across relevant reports.")
    parser.add_argument("query")
    parser.add_argument("--limit-reports", type=int, default=5)
    parser.add_argument("--limit-variables", type=int, default=20)
    parser.add_argument("--geography")
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--min-confidence", type=float)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = run_compare_concepts_auto(
        args.query,
        limit_reports=args.limit_reports,
        limit_variables=args.limit_variables,
        geography=args.geography,
        public_only=args.public_only,
        min_confidence=args.min_confidence,
    )
    if args.json_output:
        print(json.dumps(result, default=str, ensure_ascii=True, indent=2))
    else:
        print(format_human(result, debug=args.debug))


if __name__ == "__main__":
    main()
