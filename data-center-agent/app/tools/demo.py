from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text

from app.db.connection import get_demo_read_engine, get_engine
from app.db.repositories.ecosystem_organizations import EcosystemOrganizationRepository
from app.db.repositories.feedback import FeedbackRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.reports import ReportRepository
from app.db.repositories.search_index import SearchIndexRepository
from app.db.repositories.sources import SourceRepository
from app.db.repositories.variables import VariableRepository
from app.tools.registry import DEMO_TOOL_REGISTRY, UNSAFE_TOOLS_NOT_EXPOSED
from app.utils.logging import configure_logging
from app.workers.find_data import find_data as find_data_worker
from app.workers.semantic_search import semantic_search as semantic_search_worker


READ_TOOL_NAMES = {
    "find_data",
    "semantic_search",
    "get_variable_detail",
    "get_report_detail",
    "get_source_detail",
    "get_organization_detail",
    "compare_concepts",
    "list_available_filters",
    "job_status",
}
WRITE_TOOL_NAMES = {"submit_feedback"}
ALLOWED_TOOL_NAMES = READ_TOOL_NAMES | WRITE_TOOL_NAMES
ALLOWED_OBJECT_TYPES = {"variable", "dataset", "report", "source", "organization", "chunk"}
ALLOWED_FEEDBACK_TYPES = {"thumbs_up", "thumbs_down", "incorrect", "missing_data", "not_useful", "other"}


def ok(tool: str, data: Any) -> dict[str, Any]:
    return {"ok": True, "tool": tool, "data": data}


def error(tool: str, code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    payload = {"ok": False, "tool": tool, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload


def call_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    if name not in ALLOWED_TOOL_NAMES:
        return error(name, "tool_not_allowed", "Tool is not exposed to the demo UI.")
    try:
        if name in READ_TOOL_NAMES:
            with read_connection() as connection:
                return ok(name, _call_read_tool(name, args, connection))
        with get_engine().begin() as connection:
            return ok(name, _submit_feedback(args, connection))
    except ValueError as exc:
        return error(name, "invalid_args", str(exc))
    except LookupError as exc:
        return error(name, "not_found", str(exc))
    except Exception as exc:
        return error(name, "internal_error", "Tool execution failed.", {"exception": type(exc).__name__, "message": str(exc)})


@contextmanager
def read_connection():
    engine = get_demo_read_engine()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        except Exception:
            pass
        try:
            yield connection
        finally:
            transaction.rollback()


def _call_read_tool(name: str, args: dict[str, Any], connection) -> Any:
    if name == "find_data":
        def read_search(query, *, object_types, limit, hybrid, client=None, filters=None):
            return semantic_search_worker(
                query,
                object_types=object_types,
                limit=limit,
                hybrid=hybrid,
                client=client,
                filters=filters,
                connection=connection,
            )

        return find_data_worker(
            require_string(args, "query"),
            limit=optional_int(args, "limit", 10, minimum=1, maximum=25),
            public_only=bool(args.get("public_only", False)),
            geography=args.get("geography"),
            time_range=args.get("time_range"),
            search_fn=read_search,
        )
    if name == "semantic_search":
        object_types = validate_object_types(args.get("object_types"))
        return semantic_search_worker(
            require_string(args, "query"),
            object_types=object_types,
            limit=optional_int(args, "limit", 10, minimum=1, maximum=25),
            hybrid=True,
            connection=connection,
        )
    if name == "get_variable_detail":
        row = VariableRepository(connection).get_detail(require_string(args, "variable_id"))
        if not row:
            raise LookupError("Variable not found.")
        return row
    if name == "get_report_detail":
        report_id = require_string(args, "report_id")
        row = ReportRepository(connection).get_detail(report_id)
        if not row:
            raise LookupError("Report not found.")
        row["variables"] = VariableRepository(connection).list_by_report(report_id)
        return row
    if name == "get_source_detail":
        row = SourceRepository(connection).get_detail(require_string(args, "source_id"))
        if not row:
            raise LookupError("Source not found.")
        return row
    if name == "get_organization_detail":
        row = EcosystemOrganizationRepository(connection).get_detail(require_string(args, "organization_id"))
        if not row:
            raise LookupError("Organization not found.")
        return row
    if name == "compare_concepts":
        query = require_string(args, "query_or_concept_id")
        report_ids = args.get("report_ids")
        if report_ids is not None and not isinstance(report_ids, list):
            raise ValueError("report_ids must be an array when provided.")
        rows = VariableRepository(connection).compare_concepts(query, report_ids=report_ids)
        return {"query_or_concept_id": query, "report_ids": report_ids or [], "comparisons": rows}
    if name == "list_available_filters":
        return _list_available_filters(connection)
    if name == "job_status":
        row = JobRepository(connection).get(require_string(args, "job_id"))
        if not row:
            raise LookupError("Job not found.")
        return row
    raise ValueError(f"Unhandled read tool: {name}")


def _submit_feedback(args: dict[str, Any], connection) -> dict[str, Any]:
    feedback_type = require_string(args, "feedback_type")
    if feedback_type not in ALLOWED_FEEDBACK_TYPES:
        raise ValueError(f"feedback_type must be one of: {', '.join(sorted(ALLOWED_FEEDBACK_TYPES))}")
    answer_id = args.get("answer_id")
    result_id = args.get("result_id")
    if not answer_id and not result_id:
        raise ValueError("answer_id or result_id is required.")
    return FeedbackRepository(connection).create(
        {
            "answer_id": answer_id,
            "result_id": result_id,
            "feedback_type": feedback_type,
            "comment": args.get("comment"),
            "metadata": {"tool_surface": "demo"},
        }
    )


def _list_available_filters(connection) -> dict[str, Any]:
    repo = SearchIndexRepository(connection)
    object_types = [row["object_type"] for row in repo.count_by_status()]
    geographies = _distinct_values(connection, "SELECT DISTINCT geography AS value FROM search_index WHERE geography IS NOT NULL ORDER BY geography LIMIT 100")
    availability = _distinct_values(connection, "SELECT DISTINCT availability AS value FROM search_index WHERE availability IS NOT NULL ORDER BY availability LIMIT 100")
    source_types = _distinct_values(connection, "SELECT DISTINCT source_type AS value FROM sources WHERE source_type IS NOT NULL ORDER BY source_type LIMIT 100")
    return {
        "object_types": sorted(set(object_types) | {"variable", "dataset", "report", "source", "organization"}),
        "geographies": geographies,
        "availability": availability,
        "source_types": source_types,
        "max_limit": 25,
    }


def _distinct_values(connection, statement: str) -> list[str]:
    rows = connection.execute(text(statement))
    return [row._mapping["value"] for row in rows if row._mapping.get("value")]


def require_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required.")
    return value.strip()


def optional_int(args: dict[str, Any], key: str, default: int, *, minimum: int, maximum: int) -> int:
    value = args.get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer.")
    return min(max(value, minimum), maximum)


def validate_object_types(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("object_types must be an array of strings.")
    invalid = sorted(set(value) - ALLOWED_OBJECT_TYPES)
    if invalid:
        raise ValueError(f"Unsupported object_types: {', '.join(invalid)}")
    return value


def readiness_report() -> dict[str, Any]:
    samples = {
        "find_data": {"query": "startup funding in Singapore", "limit": 3, "public_only": True},
        "semantic_search": {"query": "VC deal count", "object_types": ["variable", "dataset"], "limit": 3},
        "get_variable_detail": {"variable_id": "<variable_uuid>"},
        "get_report_detail": {"report_id": "<report_uuid>"},
        "get_source_detail": {"source_id": "<source_uuid>"},
        "get_organization_detail": {"organization_id": "<organization_uuid>"},
        "compare_concepts": {"query_or_concept_id": "venture funding", "report_ids": ["<report_uuid>"]},
        "list_available_filters": {},
        "job_status": {"job_id": "<job_uuid>"},
        "submit_feedback": {"answer_id": "answer-123", "feedback_type": "thumbs_up", "comment": "Useful result."},
    }
    return {
        "implemented_tools": [tool["name"] for tool in DEMO_TOOL_REGISTRY if tool["demo_safe"]],
        "missing_tools": [],
        "unsafe_tools_not_exposed": UNSAFE_TOOLS_NOT_EXPOSED,
        "samples": [
            {
                "tool": name,
                "command": f"python -m app.tools.demo {name} --args '{json.dumps(args)}'",
                "sample_output": ok(name, {"example": True, "shape": "tool-specific structured JSON"}),
            }
            for name, args in samples.items()
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo-safe structured tool CLI.")
    parser.add_argument("tool", help="Tool name, or readiness_report.")
    parser.add_argument("--args", default="{}", help="JSON object of tool arguments.")
    args = parser.parse_args()
    configure_logging()
    if args.tool == "readiness_report":
        print(json.dumps(ok("readiness_report", readiness_report()), default=str, ensure_ascii=True, indent=2))
        return
    try:
        parsed_args = json.loads(args.args)
    except json.JSONDecodeError as exc:
        print(json.dumps(error(args.tool, "invalid_json", "Args must be a JSON object.", {"message": str(exc)}), ensure_ascii=True, indent=2))
        return
    if not isinstance(parsed_args, dict):
        print(json.dumps(error(args.tool, "invalid_args", "Args must be a JSON object."), ensure_ascii=True, indent=2))
        return
    print(json.dumps(call_tool(args.tool, parsed_args), default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
