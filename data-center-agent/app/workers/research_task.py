from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.research_task import execute_research_task
from app.tools.demo import call_tool
from app.utils.logging import configure_logging


def run_research_task(
    query: str,
    *,
    project_id: str | None = None,
    output_format: str = "json",
    output_dir: str = "exports/research_tasks",
    dry_run: bool = False,
    max_results: int = 30,
) -> dict:
    context = {"project_id": project_id} if project_id else {}
    return execute_research_task(
        query,
        tool_caller=call_tool,
        context=context,
        output_dir=Path(output_dir),
        output_format=output_format,
        dry_run=dry_run,
        max_results=max_results,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a research task using existing indexed data.")
    parser.add_argument("query")
    parser.add_argument("--project-id")
    parser.add_argument("--format", choices=["xlsx", "csv", "json"], default="json")
    parser.add_argument("--output-dir", default="exports/research_tasks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-results", type=int, default=30)
    args = parser.parse_args()
    configure_logging()
    result = run_research_task(
        args.query,
        project_id=args.project_id,
        output_format=args.format,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        max_results=args.max_results,
    )
    print(json.dumps(result, default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
