from __future__ import annotations

import csv
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from openpyxl import Workbook

from app.agents.demo_llm import DemoLLMClient, DemoLLMConfigError, DemoLLMProviderError, DemoLLMResponseError
from app.agents.query_planner import plan_query


TASK_TYPES = {
    "simple_answer",
    "find_data",
    "compare_definitions",
    "build_table",
    "create_excel",
    "aggregate_values",
    "source_audit",
    "coverage_gap_analysis",
    "research_brief",
    "organization_mapping",
    "map_query",
}
NORMALIZED_COLUMNS = [
    "metric_name",
    "concept_group",
    "geography",
    "time_period",
    "value",
    "value_status",
    "unit",
    "dimension",
    "dimension_value",
    "source_report",
    "source_url",
    "availability",
    "evidence_quote",
    "confidence_score",
    "comparability_status",
    "notes",
]


@dataclass
class ResearchTaskPlan:
    query: str
    task_type: str
    domain: str | None = None
    geography: str | None = None
    time_range: str | None = None
    metric_type: str | None = None
    output_format: str | None = None
    unit_of_analysis: str | None = None
    availability: str | None = None
    comparison_target: str | None = None
    dimension: str | None = None
    dry_run: bool = False
    max_results: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchTaskPlanner:
    def plan(self, query: str, context: dict[str, Any] | None = None, *, max_results: int = 30, dry_run: bool = False) -> ResearchTaskPlan:
        base = plan_query(query, context or {})
        detected = base.get("detected") or {}
        lowered = query.lower()
        task_type = self._task_type(lowered, detected)
        return ResearchTaskPlan(
            query=query.strip(),
            task_type=task_type,
            domain=detected.get("domain_topic"),
            geography=detected.get("geography"),
            time_range=detected.get("time_range"),
            metric_type=detected.get("metric_type"),
            output_format=self._output_format(task_type, detected),
            unit_of_analysis=detected.get("unit_of_analysis"),
            availability=detected.get("availability") or ("public_only" if "public" in lowered else None),
            comparison_target=detected.get("comparison_target"),
            dimension=self._dimension(lowered, detected),
            dry_run=dry_run,
            max_results=max_results,
        )

    def _task_type(self, lowered: str, detected: dict[str, Any]) -> str:
        if any(term in lowered for term in ("map ", "mapping", "ecosystem map")):
            return "organization_mapping" if any(term in lowered for term in ("organization", "ecosystem", "actor")) else "map_query"
        if re.search(r"\bgaps?\b", lowered) or re.search(r"\bcoverage\b", lowered):
            return "coverage_gap_analysis"
        if any(term in lowered for term in ("audit", "private sources", "source list", "what sources")):
            return "source_audit"
        if any(term in lowered for term in ("brief", "memo")):
            return "research_brief"
        if any(term in lowered for term in ("sum", "total", "aggregate", "add up")):
            return "aggregate_values"
        if any(term in lowered for term in ("compare", "definition", "definitions")):
            return "compare_definitions"
        if detected.get("output_format") == "excel" or any(term in lowered for term in ("excel", "xlsx", "workbook", "spreadsheet")):
            return "create_excel"
        if detected.get("output_format") == "table" or any(term in lowered for term in ("table", "csv", "dataset")):
            return "build_table"
        if any(term in lowered for term in ("find", "data", "metric", "indicator", "source")):
            return "find_data"
        return "simple_answer"

    def _output_format(self, task_type: str, detected: dict[str, Any]) -> str | None:
        if task_type == "create_excel":
            return "xlsx"
        if task_type == "build_table":
            return "csv"
        return detected.get("output_format")

    def _dimension(self, lowered: str, detected: dict[str, Any]) -> str | None:
        if "by stage" in lowered or "stage breakdown" in lowered:
            return "stage"
        if "by sector" in lowered or "sector breakdown" in lowered:
            return "sector"
        if "by country" in lowered:
            return "country"
        if detected.get("aggregation_intent") == "breakdown":
            return "breakdown"
        return None


def clarification_plan(query: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    plan = plan_query(query, context or {})
    if plan.get("action") != "ask_clarification":
        return None
    questions = plan.get("clarifying_questions") or []
    if not questions:
        return None
    return {
        "ok": True,
        "type": "clarification",
        "message": "Before I start the research task, I need one detail." if len(questions) == 1 else "Before I start the research task, I need a couple of details.",
        "query": query,
        "specificity": plan.get("specificity"),
        "intent": plan.get("intent"),
        "missing_dimensions": plan.get("missing_dimensions") or [],
        "clarifying_questions": questions[:2],
        "should_run_tool": False,
        "debug": {"clarification_plan": plan},
    }


class EvidencePacketBuilder:
    def build(self, query: str, task_plan: ResearchTaskPlan | dict[str, Any], retrieved: dict[str, Any]) -> dict[str, Any]:
        plan = task_plan if isinstance(task_plan, dict) else task_plan.to_dict()
        variables = [self._variable(item) for item in retrieved.get("closest_variables", []) or []]
        reports = [self._report(item) for item in retrieved.get("relevant_reports", []) or []]
        sources = [self._source(item) for item in retrieved.get("source_links", []) or []]
        organizations = [self._organization(item) for item in retrieved.get("relevant_organizations", []) or []]
        return {
            "query": query,
            "interpreted_intent": plan,
            "variables": variables,
            "reports": reports,
            "sources": sources,
            "organizations": organizations,
            "evidence_quotes": [item.get("evidence_quote") for item in variables if item.get("evidence_quote")],
            "source_urls": sorted({item.get("source_url") for item in variables + reports + sources if item.get("source_url")}),
            "availability_labels": sorted({item.get("availability") for item in variables + sources if item.get("availability")}),
            "geography_coverage": sorted({item.get("geography") for item in variables + reports if item.get("geography")}),
            "time_coverage": sorted({item.get("time_period") for item in variables if item.get("time_period")}),
            "confidence_scores": [item.get("confidence_score") for item in variables if item.get("confidence_score") is not None],
            "limitations": list(retrieved.get("limitations") or []),
        }

    def _variable(self, item: dict[str, Any]) -> dict[str, Any]:
        structured = structured_value_fields(item)
        value = structured["value"]
        unit = structured["unit"]
        value_status = structured["value_status"]
        return {
            "id": item.get("object_id") or item.get("id") or item.get("variable_id"),
            "metric_name": item.get("title") or item.get("raw_variable_name"),
            "concept_group": concept_group(item),
            "definition": item.get("definition"),
            "measurement_method": item.get("measurement_method"),
            "geography": first_present(item, "geographic_coverage", "geography"),
            "time_period": first_present(item, "temporal_coverage", "time_period", "time_coverage"),
            "value": value,
            "value_status": value_status,
            "unit": item.get("unit") or unit,
            "dimension": infer_dimension(item),
            "dimension_value": infer_dimension_value(item),
            "source_report": item.get("report_title") or item.get("source_report") or item.get("data_source"),
            "source_url": item.get("source_url"),
            "availability": item.get("availability") or "unclear",
            "evidence_quote": item.get("evidence_quote") or item.get("why_it_matched"),
            "confidence_score": item.get("confidence_score") or item.get("score"),
            "directness": "direct" if item.get("score", 0) and item.get("score", 0) >= 0.5 else "contextual",
            "notes": item.get("why_it_matched"),
        }

    def _report(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("object_id") or item.get("id") or item.get("report_id"),
            "title": item.get("title"),
            "publisher": item.get("publisher"),
            "geography": item.get("geographic_coverage") or item.get("geography"),
            "time_period": item.get("temporal_coverage") or item.get("report_year"),
            "source_url": item.get("source_url"),
            "availability": item.get("availability") or "unclear",
            "confidence_score": item.get("score"),
            "evidence_quote": item.get("evidence_quote") or item.get("why_it_matched"),
        }

    def _source(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("object_id") or item.get("source_id"),
            "title": item.get("title"),
            "source_url": item.get("source_url"),
            "availability": item.get("availability") or "unclear",
            "local_path": item.get("local_path"),
            "confidence_score": item.get("score"),
        }

    def _organization(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("object_id") or item.get("id"),
            "name": item.get("name") or item.get("title"),
            "organization_type": item.get("organization_type"),
            "geography": item.get("geography"),
            "website_url": item.get("website_url") or item.get("source_url"),
            "confidence_score": item.get("score"),
        }


class ComparabilityValidator:
    def validate(self, rows: list[dict[str, Any]], *, aggregation_requested: bool = False) -> dict[str, Any]:
        if not rows:
            return {
                "status": "insufficient_metadata",
                "issues": ["No rows available for comparison."],
                "issue_details": [{"code": "no_rows", "field": None, "message": "No rows available for comparison."}],
                "can_aggregate": False,
                "explanation": "Aggregation is blocked because there are no retrieved rows to compare.",
                "safe_aggregation_requirements": safe_aggregation_requirements(),
                "comparison_table": [],
            }
        issue_details: list[dict[str, Any]] = []
        for field_name, label in [
            ("geography", "geography"),
            ("time_period", "time period"),
            ("unit", "unit"),
            ("metric_name", "metric definition/name"),
            ("dimension", "dimension"),
        ]:
            values = {normalize_blank(row.get(field_name)) for row in rows}
            values.discard("")
            if len(values) > 1:
                issue_details.append(
                    {
                        "code": f"{field_name}_mismatch",
                        "field": field_name,
                        "message": f"Mixed {label}: {', '.join(sorted(values))}.",
                        "values": sorted(values),
                    }
                )
            elif not values:
                issue_details.append(
                    {
                        "code": f"missing_{field_name}",
                        "field": field_name,
                        "message": f"Missing {label} metadata.",
                        "values": [],
                    }
                )
        availability = {normalize_blank(row.get("availability")) for row in rows}
        if "private" in availability or "not_obtainable" in availability:
            issue_details.append(
                {
                    "code": "private_source_limitation",
                    "field": "availability",
                    "message": "Private or not-obtainable sources limit reproducible aggregation.",
                    "values": sorted(value for value in availability if value),
                }
            )
        source_urls = [row.get("source_url") for row in rows if row.get("source_url")]
        if len(source_urls) != len(set(source_urls)):
            issue_details.append(
                {
                    "code": "source_overlap_double_counting",
                    "field": "source_url",
                    "message": "Source overlap creates double-counting risk.",
                    "values": sorted({str(url) for url in source_urls if source_urls.count(url) > 1}),
                }
            )
        issues = [item["message"] for item in issue_details]
        status = self._status(issues)
        can_aggregate = aggregation_requested and status == "comparable"
        return {
            "status": status,
            "issues": issues,
            "issue_details": issue_details,
            "can_aggregate": can_aggregate,
            "explanation": comparability_explanation(status, issue_details, aggregation_requested),
            "safe_aggregation_requirements": safe_aggregation_requirements(),
            "comparison_table": comparability_table(rows),
        }

    def _status(self, issues: list[str]) -> str:
        if not issues:
            return "comparable"
        metadata_issues = [item for item in issues if item.startswith("Missing")]
        if len(metadata_issues) == len(issues):
            return "insufficient_metadata"
        if any("Mixed unit" in item or "double-counting" in item or "Private" in item for item in issues):
            return "not_comparable"
        return "partially_comparable"


class AnswerSynthesizer:
    def __init__(self, llm_client: Any | None = None, *, use_llm: bool = False) -> None:
        self.llm_client = llm_client
        self.use_llm = use_llm

    def synthesize(self, evidence_packet: dict[str, Any], comparability: dict[str, Any] | None = None) -> str:
        if self.use_llm or self.llm_client is not None:
            try:
                client = self.llm_client or DemoLLMClient()
                if hasattr(client, "synthesize_research_task"):
                    answer = client.synthesize_research_task(evidence_packet=evidence_packet, comparability=comparability or {})
                else:
                    answer = client._text_completion(self.prompt_text(evidence_packet, comparability or {}))
                if isinstance(answer, str) and answer.strip():
                    return answer.strip()
            except (DemoLLMConfigError, DemoLLMProviderError, DemoLLMResponseError, AttributeError):
                pass
        return self._fallback_synthesize(evidence_packet, comparability)

    def _fallback_synthesize(self, evidence_packet: dict[str, Any], comparability: dict[str, Any] | None = None) -> str:
        variables = evidence_packet.get("variables") or []
        reports = evidence_packet.get("reports") or []
        sources = evidence_packet.get("sources") or []
        if not variables and not reports and not sources:
            return "I could not find direct evidence for this request in the current index. The current result set has no variables, reports, or source links to cite."
        direct = [item for item in variables if item.get("directness") == "direct"]
        contextual = [item for item in variables if item.get("directness") != "direct"]
        lines = [self._direct_answer(evidence_packet, direct, variables)]
        grouped = group_by_concept(variables)
        if grouped:
            lines.append("Concept groups: " + "; ".join(f"{name} ({len(items)})" for name, items in grouped.items()) + ".")
        if direct:
            lines.append("Direct matches: " + "; ".join(self._variable_summary(item) for item in direct[:5]) + ".")
        if contextual:
            lines.append("Contextual matches: " + "; ".join(self._variable_summary(item) for item in contextual[:5]) + ".")
        cited_reports = [item.get("title") for item in reports if item.get("title")]
        cited_sources = [item.get("title") or item.get("source_url") for item in sources if item.get("title") or item.get("source_url")]
        if cited_reports or cited_sources:
            lines.append("Cited evidence: " + "; ".join((cited_reports + cited_sources)[:6]) + ".")
        labels = evidence_packet.get("availability_labels") or []
        if labels:
            lines.append("Availability: " + ", ".join(labels) + ".")
        limitations = list(evidence_packet.get("limitations") or [])
        if comparability and comparability.get("issues"):
            limitations.extend(comparability["issues"])
        if limitations:
            lines.append("Limitations: " + " ".join(limitations))
        if comparability and comparability.get("status") not in {None, "comparable"}:
            lines.append((comparability.get("explanation") or "").strip())
            requirements = comparability.get("safe_aggregation_requirements") or []
            if requirements:
                lines.append("To aggregate safely, the rows need " + "; ".join(requirements[:6]) + ".")
        lines.append("Next actions: export the evidence table, inspect source reports, or refine by geography, time period, metric type, or data availability.")
        return "\n\n".join(lines)

    def prompt_payload(self, evidence_packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "instruction": (
                "Lead with a direct answer. Distinguish direct and contextual matches. "
                "Group variables into concepts, extract values/units/years only when present, cite source/report names, "
                "label availability, explain limitations, then suggest next actions."
            ),
            "evidence_packet": evidence_packet,
        }

    def prompt_text(self, evidence_packet: dict[str, Any], comparability: dict[str, Any]) -> str:
        payload = self.prompt_payload(evidence_packet)
        return (
            payload["instruction"]
            + "\n\nUse only this evidence packet and comparability result. Do not invent values.\n\n"
            + json.dumps({"evidence_packet": evidence_packet, "comparability": comparability}, ensure_ascii=True, default=str)
        )

    def _direct_answer(self, evidence_packet: dict[str, Any], direct: list[dict[str, Any]], variables: list[dict[str, Any]]) -> str:
        query = evidence_packet.get("query") or "this request"
        count = len(variables)
        direct_count = len(direct)
        if direct_count:
            return f"Direct answer: I found {direct_count} direct variable match{'es' if direct_count != 1 else ''} and {count - direct_count} contextual match{'es' if count - direct_count != 1 else ''} for {query}."
        return f"Direct answer: I found {count} contextual variable match{'es' if count != 1 else ''} for {query}, but no high-confidence direct variable match."

    def _variable_summary(self, item: dict[str, Any]) -> str:
        bits = [str(item.get("metric_name") or "Unnamed metric")]
        if item.get("value") is not None:
            unit = f" {item.get('unit')}" if item.get("unit") else ""
            bits.append(f"value {item['value']}{unit}")
        if item.get("time_period"):
            bits.append(str(item["time_period"]))
        if item.get("geography"):
            bits.append(str(item["geography"]))
        if item.get("availability"):
            bits.append(str(item["availability"]))
        return " / ".join(bits)


class TableExcelExportService:
    def build_rows(self, evidence_packet: dict[str, Any], comparability: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        status = (comparability or {}).get("status") or "insufficient_metadata"
        rows = []
        for item in evidence_packet.get("variables") or []:
            rows.append(
                {
                    "metric_name": item.get("metric_name"),
                    "concept_group": item.get("concept_group"),
                    "geography": item.get("geography"),
                    "time_period": item.get("time_period"),
                    "value": item.get("value"),
                    "value_status": item.get("value_status"),
                    "unit": item.get("unit"),
                    "dimension": item.get("dimension"),
                    "dimension_value": item.get("dimension_value"),
                    "source_report": item.get("source_report"),
                    "source_url": item.get("source_url"),
                    "availability": item.get("availability"),
                    "evidence_quote": item.get("evidence_quote"),
                    "confidence_score": item.get("confidence_score"),
                    "comparability_status": status,
                    "notes": item.get("notes"),
                }
            )
        return rows

    def export(
        self,
        evidence_packet: dict[str, Any],
        *,
        output_dir: str | Path,
        output_format: str,
        comparability: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        stem = f"research_task_{uuid.uuid4().hex[:8]}"
        rows = self.build_rows(evidence_packet, comparability)
        if output_format == "xlsx":
            path = output_path / f"{stem}.xlsx"
            self._write_xlsx(path, evidence_packet, rows, comparability or {})
        elif output_format == "csv":
            path = output_path / f"{stem}.csv"
            self._write_csv(path, rows)
        elif output_format == "json":
            path = output_path / f"{stem}.json"
            path.write_text(json.dumps({"evidence_packet": evidence_packet, "normalized_data": rows, "comparability": comparability}, indent=2, default=str), encoding="utf-8")
        else:
            raise ValueError("output_format must be xlsx, csv, or json.")
        return {"path": str(path), "format": output_format, "row_count": len(rows)}

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=NORMALIZED_COLUMNS)
            writer.writeheader()
            writer.writerows([{column: row.get(column) for column in NORMALIZED_COLUMNS} for row in rows])

    def _write_xlsx(
        self,
        path: Path,
        evidence_packet: dict[str, Any],
        rows: list[dict[str, Any]],
        comparability: dict[str, Any],
    ) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = "normalized_data"
        append_table(ws, NORMALIZED_COLUMNS, rows)
        append_table(wb.create_sheet("source_variables"), sorted_variable_columns(evidence_packet), evidence_packet.get("variables") or [])
        append_table(wb.create_sheet("source_reports"), ["id", "title", "publisher", "geography", "time_period", "source_url", "availability", "confidence_score", "evidence_quote"], evidence_packet.get("reports") or [])
        notes = methodology_notes(evidence_packet, comparability)
        append_table(wb.create_sheet("methodology_notes"), ["note_type", "note"], notes)
        append_table(wb.create_sheet("data_gaps"), ["gap_type", "description"], data_gaps(evidence_packet, comparability))
        wb.save(path)


def execute_research_task(
    query: str,
    *,
    tool_caller: Callable[[str, dict[str, Any]], dict[str, Any]],
    context: dict[str, Any] | None = None,
    output_dir: str | Path = "exports/research_tasks",
    output_format: str | None = None,
    dry_run: bool = False,
    max_results: int = 30,
    llm_client: Any | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    clarification = clarification_plan(query, context)
    if clarification:
        return clarification
    planner = ResearchTaskPlanner()
    task_plan = planner.plan(query, context, max_results=max_results, dry_run=dry_run)
    retrieve_args = {
        "query": query,
        "limit": min(max_results, 25),
        "public_only": task_plan.availability == "public_only",
        "geography": task_plan.geography,
        "time_range": task_plan.time_range,
    }
    retrieved = {"closest_variables": [], "relevant_reports": [], "source_links": [], "relevant_organizations": [], "limitations": []}
    if not dry_run:
        if task_plan.task_type == "organization_mapping":
            tool_result = tool_caller("semantic_search", {"query": query, "object_types": ["organization"], "limit": min(max_results, 25)})
            retrieved = normalize_semantic_results(tool_result)
        elif task_plan.task_type == "compare_definitions":
            tool_result = tool_caller("compare_concepts_auto", {"query": query, "geography": task_plan.geography, "public_only": task_plan.availability == "public_only"})
            retrieved = normalize_compare_results(tool_result)
        else:
            tool_result = tool_caller("find_data", {key: value for key, value in retrieve_args.items() if value is not None})
            retrieved = normalize_find_data_results(tool_result)
    packet = EvidencePacketBuilder().build(query, task_plan, retrieved)
    export_service = TableExcelExportService()
    rows = export_service.build_rows(packet)
    comparability = ComparabilityValidator().validate(rows, aggregation_requested=task_plan.task_type == "aggregate_values")
    packet["comparability"] = comparability
    answer = AnswerSynthesizer(llm_client=llm_client, use_llm=use_llm).synthesize(packet, comparability)
    export = None
    requested_format = output_format or task_plan.output_format
    if not dry_run and requested_format in {"xlsx", "csv", "json"} and task_plan.task_type in {"build_table", "create_excel", "aggregate_values"}:
        export = export_service.export(packet, output_dir=output_dir, output_format=requested_format, comparability=comparability)
    return {
        "ok": True,
        "task_plan": task_plan.to_dict(),
        "evidence_packet": packet,
        "comparability": comparability,
        "answer": answer,
        "normalized_data": rows,
        "export": export,
        "dry_run": dry_run,
    }


def normalize_find_data_results(tool_result: dict[str, Any]) -> dict[str, Any]:
    if not tool_result.get("ok"):
        return {"closest_variables": [], "relevant_reports": [], "source_links": [], "relevant_organizations": [], "limitations": [tool_result.get("error", {}).get("message", "Tool failed.")]}
    data = tool_result.get("data") or {}
    return {
        "closest_variables": data.get("closest_variables") or [],
        "relevant_reports": data.get("relevant_reports") or [],
        "source_links": data.get("source_links") or [],
        "relevant_organizations": data.get("relevant_organizations") or [],
        "limitations": [item for item in [data.get("warning")] if item],
    }


def normalize_compare_results(tool_result: dict[str, Any]) -> dict[str, Any]:
    if not tool_result.get("ok"):
        return normalize_find_data_results(tool_result)
    data = tool_result.get("data") or {}
    return {
        "closest_variables": data.get("closest_variables") or [],
        "relevant_reports": data.get("selected_reports") or [],
        "source_links": [],
        "relevant_organizations": [],
        "limitations": data.get("limitations") or [],
    }


def normalize_semantic_results(tool_result: dict[str, Any]) -> dict[str, Any]:
    if not tool_result.get("ok"):
        return normalize_find_data_results(tool_result)
    rows = (tool_result.get("data") or {}).get("results") or []
    organizations = []
    sources = []
    for row in rows:
        if row.get("object_type") == "organization":
            metadata = row.get("metadata") or {}
            organizations.append(
                {
                    "object_id": row.get("object_id"),
                    "name": row.get("title"),
                    "organization_type": metadata.get("organization_type"),
                    "geography": row.get("geography"),
                    "website_url": metadata.get("website_url") or row.get("source_url"),
                    "score": row.get("score"),
                }
            )
        elif row.get("source_url"):
            sources.append({"title": row.get("title"), "source_url": row.get("source_url"), "availability": row.get("availability"), "score": row.get("score")})
    return {"closest_variables": [], "relevant_reports": [], "source_links": sources, "relevant_organizations": organizations, "limitations": []}


def extract_numeric_value(text: str) -> tuple[float | None, str | None]:
    if not text:
        return None, None
    match = re.search(r"(?P<prefix>[$€£])?\b(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<suffix>%|percent|million|billion|mn|bn)?", text, re.I)
    if not match:
        return None, None
    number = float(match.group("number").replace(",", ""))
    suffix = match.group("suffix")
    prefix = match.group("prefix")
    unit = prefix or suffix
    return number, unit


def structured_value_fields(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    value = first_present(item, "value", "metric_value", "numeric_value", "amount")
    unit = first_present(item, "unit", "value_unit", "currency", "measurement_unit")
    if value is None and metadata:
        value = first_present(metadata, "value", "metric_value", "numeric_value", "amount")
    if unit is None and metadata:
        unit = first_present(metadata, "unit", "value_unit", "currency", "measurement_unit")
    parsed_value = parse_number(value)
    if parsed_value is not None:
        return {"value": parsed_value, "unit": unit, "value_status": "structured"}
    fallback_value, fallback_unit = extract_numeric_value(item.get("evidence_quote") or item.get("why_it_matched") or "")
    if fallback_value is not None:
        return {"value": fallback_value, "unit": unit or fallback_unit, "value_status": "extracted_from_evidence"}
    return {"value": None, "unit": unit, "value_status": "not_extracted"}


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", value)
        if match:
            return float(match.group(0).replace(",", ""))
    return None


def concept_group(item: dict[str, Any]) -> str | None:
    text = " ".join(str(item.get(key) or "") for key in ("title", "definition", "measurement_method")).lower()
    if any(term in text for term in ("stage", "seed", "series a")):
        return "stage breakdown"
    if "sector" in text:
        return "sector breakdown"
    if any(term in text for term in ("deal", "round")):
        return "deal activity"
    if any(term in text for term in ("funding", "investment", "capital")):
        return "funding amount"
    if any(term in text for term in ("exit", "ipo", "acquisition")):
        return "exits"
    return item.get("concept_group") or "other"


def infer_dimension(item: dict[str, Any]) -> str | None:
    text = " ".join(str(item.get(key) or "") for key in ("title", "definition", "measurement_method")).lower()
    if "stage" in text or "seed" in text or "series a" in text:
        return "stage"
    if "sector" in text:
        return "sector"
    if "country" in text:
        return "country"
    return None


def infer_dimension_value(item: dict[str, Any]) -> str | None:
    text = " ".join(str(item.get(key) or "") for key in ("title", "definition")).lower()
    for value in ("pre-seed", "seed", "series a", "series b", "growth", "late stage"):
        if value in text:
            return value.title()
    return None


def group_by_concept(variables: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in variables:
        grouped.setdefault(item.get("concept_group") or "other", []).append(item)
    return grouped


def normalize_blank(value: Any) -> str:
    return str(value or "").strip().lower()


def comparability_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "metric_name": row.get("metric_name"),
            "geography": row.get("geography"),
            "time_period": row.get("time_period"),
            "unit": row.get("unit"),
            "dimension": row.get("dimension"),
            "source_report": row.get("source_report"),
            "source_url": row.get("source_url"),
            "availability": row.get("availability"),
            "value_status": row.get("value_status"),
        }
        for row in rows
    ]


def comparability_explanation(status: str, issue_details: list[dict[str, Any]], aggregation_requested: bool) -> str:
    if status == "comparable":
        return "The rows appear comparable on geography, time period, unit, metric name, dimension, source overlap, and availability."
    prefix = "Aggregation is blocked" if aggregation_requested else "Comparability is limited"
    if not issue_details:
        return f"{prefix} because the current metadata is insufficient."
    reasons = []
    for item in issue_details:
        code = item.get("code")
        if code == "unit_mismatch":
            reasons.append("units differ across rows")
        elif code == "geography_mismatch":
            reasons.append("geographies differ across rows")
        elif code == "time_period_mismatch":
            reasons.append("time periods differ across rows")
        elif code == "metric_name_mismatch":
            reasons.append("metric definitions or names differ")
        elif code == "dimension_mismatch":
            reasons.append("dimensions differ")
        elif code == "source_overlap_double_counting":
            reasons.append("source overlap creates double-counting risk")
        elif code == "private_source_limitation":
            reasons.append("private/proprietary availability limits reproducibility")
        elif str(code).startswith("missing_"):
            reasons.append(item.get("message", "required metadata is missing").rstrip(".").lower())
        else:
            reasons.append(item.get("message", "metadata issue").rstrip("."))
    return f"{prefix} because " + "; ".join(reasons) + "."


def safe_aggregation_requirements() -> list[str]:
    return [
        "same geography",
        "same time period",
        "same unit/currency",
        "same metric definition and funding type",
        "same dimension and dimension value",
        "non-overlapping source coverage",
        "clear public/obtainable availability or explicit private-source caveat",
    ]


def append_table(ws, columns: list[str], rows: list[dict[str, Any]]) -> None:
    ws.append(columns)
    for row in rows:
        ws.append([row.get(column) for column in columns])


def sorted_variable_columns(evidence_packet: dict[str, Any]) -> list[str]:
    preferred = [
        "id",
        "metric_name",
        "concept_group",
        "definition",
        "measurement_method",
        "geography",
        "time_period",
        "value",
        "value_status",
        "unit",
        "dimension",
        "dimension_value",
        "source_report",
        "source_url",
        "availability",
        "evidence_quote",
        "confidence_score",
        "directness",
        "notes",
    ]
    keys = set()
    for item in evidence_packet.get("variables") or []:
        keys.update(item)
    return preferred + sorted(keys - set(preferred))


def methodology_notes(evidence_packet: dict[str, Any], comparability: dict[str, Any]) -> list[dict[str, str]]:
    plan = evidence_packet.get("interpreted_intent") or {}
    notes = [
        {"note_type": "query", "note": str(evidence_packet.get("query") or "")},
        {"note_type": "task_type", "note": str(plan.get("task_type") or "")},
        {"note_type": "method", "note": "Rows are normalized from retrieved variables only; no new data was ingested and no values were invented."},
        {"note_type": "method", "note": "Numeric values are extracted from existing evidence quotes when present; arithmetic is performed only after comparability validation."},
        {"note_type": "comparability", "note": str(comparability.get("status") or "insufficient_metadata")},
    ]
    for issue in comparability.get("issues") or []:
        notes.append({"note_type": "comparability_issue", "note": issue})
    return notes


def data_gaps(evidence_packet: dict[str, Any], comparability: dict[str, Any]) -> list[dict[str, str]]:
    gaps = []
    if not evidence_packet.get("variables"):
        gaps.append({"gap_type": "variables", "description": "No structured variables were retrieved."})
    for field_name, label in [("geography", "geography"), ("time_period", "time coverage"), ("unit", "unit"), ("value", "numeric value")]:
        missing = [item.get("metric_name") or "Unnamed metric" for item in evidence_packet.get("variables") or [] if item.get(field_name) in (None, "")]
        if missing:
            gaps.append({"gap_type": field_name, "description": f"Missing {label} for {len(missing)} variable(s): {', '.join(missing[:5])}."})
    for issue in comparability.get("issues") or []:
        gaps.append({"gap_type": "comparability", "description": issue})
    return gaps or [{"gap_type": "none", "description": "No obvious metadata gaps detected in retrieved rows."}]
