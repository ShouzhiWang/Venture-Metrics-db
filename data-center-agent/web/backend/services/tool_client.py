from __future__ import annotations

import logging
from typing import Any

from app.tools.demo import call_tool


LOGGER = logging.getLogger(__name__)
SAFE_WEB_TOOLS = {
    "find_data",
    "semantic_search",
    "compare_concepts_auto",
    "get_variable_detail",
    "get_report_detail",
    "get_source_detail",
    "get_organization_detail",
    "list_available_filters",
    "submit_feedback",
    "read_source",
    "analyze_table",
}


def call_demo_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in SAFE_WEB_TOOLS:
        LOGGER.warning("Rejected unsafe web tool call: %s", name)
        return {"ok": False, "tool": name, "error": {"code": "tool_not_allowed", "message": "Tool is not exposed to the website."}}
    LOGGER.info("Web tool call: %s", name)
    return call_tool(name, args or {})
