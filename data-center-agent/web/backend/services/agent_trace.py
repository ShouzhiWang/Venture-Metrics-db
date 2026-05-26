from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


TraceUpdateCallback = Callable[[list[dict[str, Any]]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_TOOL_START_LABELS: dict[str, tuple[str, str]] = {
    "find_data": ("Calling find_data", "Searching variables, reports, sources, and organizations"),
    "semantic_search": ("Calling semantic_search", "Searching indexed records"),
    "compare_concepts_auto": ("Calling compare_concepts_auto", "Finding comparable reports and variables"),
    "get_variable_detail": ("Fetching variable detail", "Loading variable evidence"),
    "get_report_detail": ("Fetching report detail", "Loading report metadata"),
    "get_source_detail": ("Fetching source detail", "Loading source metadata"),
    "get_organization_detail": ("Fetching organization detail", "Loading organization metadata"),
}


class AgentTraceCollector:
    def __init__(self, on_update: TraceUpdateCallback | None = None) -> None:
        self._events: list[dict[str, Any]] = []
        self._tool_started_at: dict[str, float] = {}
        self._on_update = on_update

    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def _notify(self) -> None:
        if self._on_update:
            self._on_update(self.events())

    def _append(
        self,
        *,
        event_type: str,
        status: str,
        label: str,
        detail: str = "",
        tool_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "timestamp": _utc_now(),
            "type": event_type,
            "status": status,
            "label": label,
            "detail": detail,
        }
        if tool_name:
            event["tool_name"] = tool_name
        if metadata:
            event["metadata"] = metadata
        self._events.append(event)
        self._notify()
        return event

    def planning_started(self) -> None:
        self._append(
            event_type="planning",
            status="running",
            label="Planning query",
            detail="Analyzing your question and selecting data tools",
        )

    def planning_complete(self, intent: str, tool_names: list[str]) -> None:
        self._mark_last_completed("planning")
        tools = ", ".join(tool_names) if tool_names else "none"
        self._append(
            event_type="planning",
            status="completed",
            label="Query planned",
            detail=f"Query planner classified intent: {intent}; selected tools: {tools}",
            metadata={"intent": intent},
        )

    def tool_selected(self, tool_names: list[str]) -> None:
        if not tool_names:
            return
        self._append(
            event_type="planning",
            status="completed",
            label="Tools selected",
            detail=", ".join(tool_names),
            metadata={"intent": tool_names[0] if len(tool_names) == 1 else "multi_tool"},
        )

    def tool_start(self, tool_name: str) -> None:
        self._tool_started_at[tool_name] = time.monotonic()
        label, detail = _TOOL_START_LABELS.get(tool_name, (f"Calling {tool_name}", f"Running {tool_name}"))
        self._append(event_type="tool_start", status="running", label=label, detail=detail, tool_name=tool_name)

    def tool_complete(self, tool_name: str, data: dict[str, Any]) -> None:
        duration_ms = _duration_ms(self._tool_started_at.pop(tool_name, None))
        counts = _counts_from_tool_data(tool_name, data)
        detail = _format_retrieval_detail(counts)
        metadata = {**counts}
        if duration_ms is not None:
            metadata["duration_ms"] = duration_ms
        self._mark_tool_start_completed(tool_name)
        self._append(
            event_type="tool_complete",
            status="completed",
            label=_tool_complete_label(tool_name),
            detail=detail,
            tool_name=tool_name,
            metadata=metadata,
        )
        self._append_compare_internals(data)
        self._append_compare_fallbacks(tool_name, data)
        self._append_data_warnings(data)

    def tool_failed(self, tool_name: str, message: str) -> None:
        duration_ms = _duration_ms(self._tool_started_at.pop(tool_name, None))
        metadata: dict[str, Any] = {}
        if duration_ms is not None:
            metadata["duration_ms"] = duration_ms
        self._mark_tool_start_failed(tool_name)
        self._append(
            event_type="error",
            status="failed",
            label=f"{tool_name} failed",
            detail=sanitize_trace_detail(message),
            tool_name=tool_name,
            metadata=metadata or None,
        )

    def fallback(self, label: str, detail: str) -> None:
        self._append(event_type="fallback", status="completed", label=label, detail=sanitize_trace_detail(detail))

    def warning(self, label: str, detail: str) -> None:
        self._append(event_type="warning", status="completed", label=label, detail=sanitize_trace_detail(detail))

    def answer_generation_started(self) -> None:
        self._append(
            event_type="answer_generation",
            status="running",
            label="Generating answer summary",
            detail="Synthesizing evidence-backed response",
        )

    def answer_generation_complete(self) -> None:
        self._mark_last_completed("answer_generation")
        self._append(
            event_type="answer_generation",
            status="completed",
            label="Answer ready",
            detail="Response prepared for review",
        )

    def rank_results(self, counts: dict[str, int]) -> None:
        detail = _format_retrieval_detail(counts)
        if not detail:
            detail = "Ranked available evidence"
        self._append(
            event_type="tool_progress",
            status="completed",
            label="Ranked evidence-backed results",
            detail=detail,
            metadata=counts,
        )

    def error_event(self, label: str, detail: str) -> None:
        self._append(
            event_type="error",
            status="failed",
            label=label,
            detail=sanitize_trace_detail(detail),
        )

    def _mark_last_completed(self, event_type: str) -> None:
        for event in reversed(self._events):
            if event["type"] == event_type and event["status"] == "running":
                event["status"] = "completed"
                self._notify()
                return

    def _mark_tool_start_completed(self, tool_name: str) -> None:
        for event in reversed(self._events):
            if event.get("tool_name") == tool_name and event["type"] == "tool_start" and event["status"] == "running":
                event["status"] = "completed"
                self._notify()
                return

    def _mark_tool_start_failed(self, tool_name: str) -> None:
        for event in reversed(self._events):
            if event.get("tool_name") == tool_name and event["type"] == "tool_start" and event["status"] == "running":
                event["status"] = "failed"
                self._notify()
                return

    def _append_compare_internals(self, data: dict[str, Any]) -> None:
        chain = (data.get("metadata") or {}).get("tool_chain")
        if not isinstance(chain, list):
            return
        for step in chain:
            if not isinstance(step, str) or not step.strip():
                continue
            label, detail = _TOOL_START_LABELS.get(step, (f"Ran {step}", f"Completed {step}"))
            self._append(
                event_type="tool_progress",
                status="completed",
                label=label,
                detail=detail,
                tool_name=step,
            )

    def _append_compare_fallbacks(self, tool_name: str, data: dict[str, Any]) -> None:
        if tool_name != "compare_concepts_auto":
            return
        status = data.get("status")
        reports = data.get("selected_reports") or []
        if status == "insufficient_reports":
            self.fallback(
                "Limited comparison coverage",
                "compare_concepts_auto found fewer than two comparable reports; returning partial matches.",
            )
        elif status == "no_results":
            self.fallback(
                "Comparison unavailable",
                "No comparable variables were found; related reports may still be available.",
            )
        if reports:
            titles = [str(r.get("title") or "Report").strip() for r in reports[:3] if isinstance(r, dict)]
            if titles:
                detail = f"Selected {len(reports)} report{'s' if len(reports) != 1 else ''}"
                if titles:
                    detail += f": {', '.join(titles)}"
                self._append(
                    event_type="tool_progress",
                    status="completed",
                    label="Reports selected for comparison",
                    detail=detail,
                    tool_name="compare_concepts_auto",
                    metadata={"report_count": len(reports)},
                )

    def _append_data_warnings(self, data: dict[str, Any]) -> None:
        warning = data.get("warning")
        if isinstance(warning, str) and warning.strip():
            self.warning("Search warning", warning.strip())
        for item in data.get("limitations") or []:
            if isinstance(item, str) and item.strip():
                self.warning("Limitation noted", item.strip())


def attach_tool_trace(response: dict[str, Any], trace: AgentTraceCollector | None) -> dict[str, Any]:
    if trace is not None:
        response["tool_trace"] = trace.events()
    elif "tool_trace" not in response:
        response["tool_trace"] = []
    return response


def sanitize_trace_detail(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "The request could not be completed."
    text = re.sub(r"(?i)(traceback|stack trace|file \"/).*", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:500] if text else "The request could not be completed."


def _duration_ms(started_at: float | None) -> int | None:
    if started_at is None:
        return None
    return int((time.monotonic() - started_at) * 1000)


def _counts_from_tool_data(tool_name: str, data: dict[str, Any]) -> dict[str, int]:
    counts = {
        "variable_count": 0,
        "report_count": 0,
        "source_count": 0,
        "organization_count": 0,
    }
    if tool_name == "find_data":
        counts["variable_count"] = len(data.get("closest_variables") or [])
        counts["report_count"] = len(data.get("relevant_reports") or [])
        counts["source_count"] = len(data.get("source_links") or [])
        counts["organization_count"] = len(data.get("relevant_organizations") or [])
    elif tool_name == "semantic_search":
        rows = data.get("results") or []
        if any(isinstance(row, dict) and row.get("object_type") == "organization" for row in rows):
            counts["organization_count"] = len(rows)
        else:
            counts["source_count"] = len(rows)
    elif tool_name == "compare_concepts_auto":
        counts["variable_count"] = len(data.get("closest_variables") or [])
        counts["report_count"] = len(data.get("selected_reports") or [])
        if data.get("comparison"):
            counts["comparison_count"] = 1
    return counts


def _format_retrieval_detail(counts: dict[str, int]) -> str:
    parts: list[str] = []
    if counts.get("variable_count"):
        n = counts["variable_count"]
        parts.append(f"{n} variable{'s' if n != 1 else ''}")
    if counts.get("report_count"):
        n = counts["report_count"]
        parts.append(f"{n} report{'s' if n != 1 else ''}")
    if counts.get("source_count"):
        n = counts["source_count"]
        parts.append(f"{n} source{'s' if n != 1 else ''}")
    if counts.get("organization_count"):
        n = counts["organization_count"]
        parts.append(f"{n} organization{'s' if n != 1 else ''}")
    if not parts:
        return "No structured matches retrieved"
    return f"Retrieved {', '.join(parts)}"


def _tool_complete_label(tool_name: str) -> str:
    labels = {
        "find_data": "find_data completed",
        "semantic_search": "semantic_search completed",
        "compare_concepts_auto": "compare_concepts_auto completed",
    }
    return labels.get(tool_name, f"{tool_name} completed")
