from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


METRIC_QUESTIONS = {
    "metric_type": {
        "dimension": "metric_type",
        "question": "Which metric type do you want?",
        "options": [
            "Funding amount",
            "Deal count",
            "Median/average round size",
            "Stage breakdown",
            "Sector breakdown",
            "Exits",
        ],
    },
    "geography": {
        "dimension": "geography",
        "question": "Which market should I focus on?",
        "options": ["Singapore", "Hong Kong", "Shenzhen", "India", "Southeast Asia", "China", "All Asia"],
    },
    "time_range": {
        "dimension": "time_range",
        "question": "What time period should I use?",
        "options": ["Latest available", "Past 5 years", "Past 10 years", "Specific year", "All available years"],
    },
    "availability": {
        "dimension": "availability",
        "question": "Should I include private/proprietary data sources?",
        "options": ["Public/obtainable only", "Include private sources", "Show both, clearly labeled"],
    },
    "output_format": {
        "dimension": "output_format",
        "question": "What output do you want?",
        "options": ["Short answer", "Comparison table", "Excel workbook", "Source list", "Research brief"],
    },
    "unit_of_analysis": {
        "dimension": "unit_of_analysis",
        "question": "What level of data do you need?",
        "options": [
            "Company-level",
            "Deal-level",
            "City/country-level indicators",
            "Organization/ecosystem actors",
            "Report-level sources",
        ],
    },
    "domain_topic": {
        "dimension": "domain_topic",
        "question": "Which topic should I focus on?",
        "options": [
            "Startup funding",
            "Innovation metrics",
            "SME digital adoption",
            "R&D indicators",
            "Ecosystem organizations",
            "Data sources",
        ],
    },
}

GEOGRAPHIES = {
    "Singapore": ("singapore",),
    "Hong Kong": ("hong kong", "hk"),
    "Shenzhen": ("shenzhen",),
    "India": ("india",),
    "Southeast Asia": ("southeast asia", "south-east asia", "asean", "sea "),
    "China": ("china",),
    "All Asia": ("asia", "asian"),
    "Malaysia": ("malaysia",),
    "Indonesia": ("indonesia",),
    "Vietnam": ("vietnam",),
    "Thailand": ("thailand",),
    "Japan": ("japan",),
    "Korea": ("korea",),
}
DOMAIN_TERMS = {
    "startup": ("startup", "startups", "vc", "venture", "funding", "deal", "round", "exits", "unicorn"),
    "innovation": ("innovation", "patent", "r&d", "research", "ecosystem"),
    "sme": ("sme", "small business", "digital adoption"),
    "ai": ("ai", "artificial intelligence"),
}
METRIC_TERMS = {
    "funding_amount": ("funding amount", "investment", "capital", "expenditure", "spend", "value", "valuation"),
    "deal_count": ("deal count", "number of deals", "count", "births"),
    "round_size": ("median", "average", "round size"),
    "stage_breakdown": ("by stage", "stage breakdown", "seed", "series a"),
    "sector_breakdown": ("by sector", "sector breakdown"),
    "exits": ("exit", "exits", "ipo", "acquisition"),
    "percentage": ("percentage", "percent", "%", "share", "proportion", "intensity"),
}
TIME_TERMS = ("trend", "trends", "over time", "evolution", "by year", "year-by-year", "historical")
OUTPUT_TERMS = {
    "excel": ("excel", "xlsx", "workbook", "spreadsheet"),
    "table": ("table",),
    "brief": ("brief", "memo"),
    "source_list": ("source list", "sources"),
}
COMPARISON_TERMS = ("compare", "differ", "different", "differences", "comparable", "definition differences")
ORG_TERMS = (
    "organization",
    "organizations",
    "organisation",
    "organisations",
    "association",
    "accelerator",
    "incubator",
    "agency",
    "directory",
    "ecosystem actors",
)
GENERIC_DATA_TERMS = ("data", "dataset", "data set", "metrics", "indicators")


@dataclass
class QueryPlan:
    query: str
    specificity: str
    action: str
    intent: str
    detected: dict[str, Any]
    missing_dimensions: list[str] = field(default_factory=list)
    clarifying_questions: list[dict[str, Any]] = field(default_factory=list)
    refinement_chips: list[dict[str, Any]] = field(default_factory=list)
    inferred_query: str = ""
    should_run_tool: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ambiguity_level"] = self.specificity
        data["should_ask_clarifying_question"] = self.action == "ask_clarification"
        data["extracted_filters"] = {
            "geography": self.detected.get("geography"),
            "time_range": self.detected.get("time_range"),
            "public_only": self.detected.get("availability") == "public_only",
            "domain": self.detected.get("domain_topic"),
            "preferred_metric_type": _legacy_metric_type(self.detected.get("metric_type")),
            "output_format": self.detected.get("output_format"),
            "unit_of_analysis": self.detected.get("unit_of_analysis"),
        }
        return data


def plan_query(query: str, context: dict | None = None) -> dict[str, Any]:
    text = (query or "").strip()
    lowered = text.lower()
    context = context or {}
    inferred_bits = _project_inferences(context)
    detected = {
        "geography": _detect_geography(lowered, context) or inferred_bits.get("geography"),
        "time_range": _detect_time_range(text),
        "metric_type": _detect_metric_type(lowered),
        "domain_topic": _detect_domain(lowered) or inferred_bits.get("domain_topic"),
        "availability": "public_only" if _is_public_only(lowered, context) else None,
        "output_format": _detect_output_format(lowered),
        "unit_of_analysis": _detect_unit_of_analysis(lowered),
        "comparison_target": _detect_comparison_target(lowered),
        "aggregation_intent": _detect_aggregation_intent(lowered),
    }
    intent = _detect_intent(lowered, detected)
    missing = _missing_dimensions(lowered, detected, intent)
    specificity = _specificity(lowered, detected, missing, intent)
    action = {
        "high": "ask_clarification",
        "medium": "search_with_refinement",
        "low": "search_directly",
    }[specificity]
    questions = _select_questions(lowered, missing, detected, intent, action)
    refinement_chips = _refinement_chips(missing, detected, intent) if action == "search_with_refinement" else []
    tool_calls = _tool_calls(text, intent, detected) if action != "ask_clarification" and text else []
    return QueryPlan(
        query=text,
        specificity=specificity,
        action=action,
        intent=intent,
        detected=detected,
        missing_dimensions=missing,
        clarifying_questions=questions,
        refinement_chips=refinement_chips,
        inferred_query=_inferred_query(text, inferred_bits),
        should_run_tool=action != "ask_clarification",
        tool_calls=tool_calls,
    ).to_dict()


def refined_query(base_query: str, option: str) -> str:
    base = " ".join((base_query or "").split())
    selection = " ".join((option or "").split())
    if not base:
        return selection
    if not selection or selection.lower() in base.lower():
        return base
    return f"{base}, {selection}"


def _detect_intent(lowered: str, detected: dict[str, Any]) -> str:
    if any(term in lowered for term in COMPARISON_TERMS):
        return "compare_concepts"
    if any(term in lowered for term in ORG_TERMS) or detected.get("unit_of_analysis") == "organization/ecosystem actors":
        return "find_organizations"
    if detected.get("output_format") == "excel":
        return "create_excel"
    if detected.get("output_format") in {"table", "dataset"}:
        return "build_table"
    if "source" in lowered and any(term in lowered for term in ("audit", "list", "where", "private", "public")):
        return "source_audit"
    if lowered:
        return "find_data"
    return "unknown"


def _detect_metric_type(lowered: str) -> str | None:
    for metric_type, terms in METRIC_TERMS.items():
        if any(term in lowered for term in terms):
            return metric_type
    return None


def _detect_geography(lowered: str, context: dict[str, Any]) -> str | None:
    selected = (context.get("selected_filters") or {}).get("geography")
    if selected:
        return str(selected)
    for geography, terms in GEOGRAPHIES.items():
        if any(term in lowered for term in terms):
            return geography
    return None


def _detect_time_range(query: str) -> str | None:
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    if years:
        return "-".join([years[0], years[-1]]) if len(years) > 1 else years[0]
    lowered = query.lower()
    if "latest" in lowered:
        return "latest available"
    if "past 5" in lowered or "last 5" in lowered:
        return "past 5 years"
    if "past 10" in lowered or "last 10" in lowered:
        return "past 10 years"
    return None


def _detect_domain(lowered: str) -> str | None:
    if " ".join(lowered.split()) in {"startup data", "innovation ecosystem", "funding trends"}:
        return None
    for domain, terms in DOMAIN_TERMS.items():
        if any(term in lowered for term in terms):
            if domain == "startup" and ("funding" in lowered or "vc" in lowered or "venture" in lowered):
                return "startup funding"
            return domain
    return None


def _detect_output_format(lowered: str) -> str | None:
    for output, terms in OUTPUT_TERMS.items():
        if any(term in lowered for term in terms):
            return output
    return None


def _detect_unit_of_analysis(lowered: str) -> str | None:
    if "company" in lowered or "companies" in lowered:
        return "company-level"
    if "deal" in lowered or "round" in lowered:
        return "deal-level"
    if "city" in lowered or "country" in lowered or "countries" in lowered:
        return "city/country-level indicators"
    if any(term in lowered for term in ORG_TERMS):
        return "organization/ecosystem actors"
    if "report" in lowered:
        return "report-level sources"
    return None


def _detect_comparison_target(lowered: str) -> str | None:
    if " by country" in lowered:
        return "country"
    if " across " in lowered:
        return lowered.split(" across ", 1)[1].strip()[:80] or None
    return None


def _detect_aggregation_intent(lowered: str) -> str | None:
    if any(term in lowered for term in ("by stage", "by sector", "by country", "breakdown")):
        return "breakdown"
    if any(term in lowered for term in TIME_TERMS):
        return "trend"
    if "compare" in lowered:
        return "comparison"
    return None


def _is_public_only(lowered: str, context: dict[str, Any]) -> bool:
    return "public" in lowered or "obtainable" in lowered or bool((context.get("selected_filters") or {}).get("public_only"))


def _project_inferences(context: dict[str, Any]) -> dict[str, str]:
    project_text = " ".join(
        str(context.get(key) or "") for key in ("project_title", "research_question", "project_description")
    ).lower()
    return {
        key: value
        for key, value in {
            "geography": _detect_geography(project_text, {}),
            "domain_topic": _detect_domain(project_text),
        }.items()
        if value
    }


def _missing_dimensions(lowered: str, detected: dict[str, Any], intent: str) -> list[str]:
    missing: list[str] = []
    if not detected.get("domain_topic") and _needs_domain(lowered, intent):
        missing.append("domain_topic")
    if not detected.get("geography") and _needs_geography(lowered, detected, intent):
        missing.append("geography")
    if _asks_for_dataset(lowered) and not detected.get("output_format"):
        missing.append("output_format")
    if _asks_for_dataset(lowered) and not detected.get("unit_of_analysis"):
        missing.append("unit_of_analysis")
    if _asks_trends(lowered) and not detected.get("time_range"):
        missing.append("time_range")
    if _needs_metric(lowered, detected, intent):
        missing.append("metric_type")
    if detected.get("availability") != "public_only" and "private" in lowered and not detected.get("availability"):
        missing.append("availability")
    return _dedupe(missing)


def _needs_domain(lowered: str, intent: str) -> bool:
    if intent == "unknown":
        return True
    if " ".join(lowered.split()) in {"startup data", "innovation ecosystem", "funding trends", "make me a dataset"}:
        return True
    return bool(any(term in lowered for term in GENERIC_DATA_TERMS)) and not any(term in lowered for term in COMPARISON_TERMS)


def _needs_geography(lowered: str, detected: dict[str, Any], intent: str) -> bool:
    if intent in {"compare_concepts", "source_audit"}:
        return False
    if detected.get("comparison_target") == "country":
        return False
    return bool(detected.get("domain_topic")) and any(term in lowered for term in ("funding", "startup", "sme", "innovation", "ecosystem"))


def _needs_metric(lowered: str, detected: dict[str, Any], intent: str) -> bool:
    if intent in {"compare_concepts", "find_organizations", "source_audit"}:
        return False
    if detected.get("metric_type"):
        return False
    if detected.get("output_format") in {"excel", "dataset", "table"}:
        return False
    if _asks_trends(lowered):
        return False
    return bool(detected.get("domain_topic") and detected.get("geography"))


def _asks_for_dataset(lowered: str) -> bool:
    return any(term in lowered for term in ("make me a dataset", "create a dataset", "dataset", "excel", "workbook", "spreadsheet"))


def _asks_trends(lowered: str) -> bool:
    return any(term in lowered for term in TIME_TERMS)


def _specificity(lowered: str, detected: dict[str, Any], missing: list[str], intent: str) -> str:
    if intent == "unknown" or not lowered:
        return "high"
    if _very_broad(lowered, detected, missing):
        return "high"
    if _asks_for_dataset(lowered) and detected.get("output_format") == "excel" and detected.get("geography") and detected.get("metric_type"):
        return "low"
    if _asks_for_dataset(lowered) and ("output_format" in missing or "unit_of_analysis" in missing or "geography" in missing):
        return "high"
    if "time_range" in missing and _asks_trends(lowered) and not detected.get("metric_type"):
        return "high"
    if "domain_topic" in missing:
        return "high"
    if detected.get("comparison_target") == "country":
        return "medium"
    if not missing:
        return "low"
    if set(missing).issubset({"metric_type", "time_range", "availability"}):
        return "medium"
    if detected.get("domain_topic") and detected.get("geography"):
        return "medium"
    if detected.get("domain_topic") and set(missing).issubset({"geography"}):
        return "medium"
    return "high"


def _very_broad(lowered: str, detected: dict[str, Any], missing: list[str]) -> bool:
    compact = " ".join(lowered.split())
    broad_phrases = {
        "startup data",
        "innovation ecosystem",
        "funding trends",
        "make me a dataset",
        "make me a data set",
        "analyze singapore startups",
    }
    if compact in broad_phrases:
        return True
    word_count = len(compact.split())
    return word_count <= 3 and len(missing) >= 2 and not detected.get("metric_type")


def _select_questions(
    lowered: str,
    missing: list[str],
    detected: dict[str, Any],
    intent: str,
    action: str,
) -> list[dict[str, Any]]:
    if action == "search_directly":
        return []
    priority = ["domain_topic", "geography", "metric_type", "time_range", "output_format", "unit_of_analysis", "availability"]
    if not detected.get("domain_topic"):
        priority = ["domain_topic", "geography", "metric_type", "time_range", "output_format", "unit_of_analysis", "availability"]
    elif _asks_for_dataset(lowered):
        priority = ["output_format", "unit_of_analysis", "geography", "metric_type", "time_range"]
    elif _asks_trends(lowered):
        priority = ["time_range", "metric_type", "geography"]
    elif detected.get("domain_topic") and not detected.get("geography"):
        priority = ["geography", "metric_type", "time_range"]
    elif detected.get("domain_topic") and detected.get("geography"):
        priority = ["metric_type", "time_range", "unit_of_analysis"]
    if intent == "find_organizations":
        priority = ["geography", "domain_topic"]
    selected = [dimension for dimension in priority if dimension in missing][:2]
    return [_question(dimension) for dimension in selected]


def _refinement_chips(missing: list[str], detected: dict[str, Any], intent: str) -> list[dict[str, Any]]:
    dimensions = [dimension for dimension in ("metric_type", "time_range", "unit_of_analysis", "availability", "geography") if dimension in missing]
    if not dimensions and intent == "find_data" and detected.get("metric_type"):
        dimensions = ["metric_type"]
    chips = []
    for dimension in dimensions[:2]:
        question = _question(dimension)
        chips.append(question)
    return chips


def _question(dimension: str) -> dict[str, Any]:
    template = METRIC_QUESTIONS[dimension]
    return {
        "dimension": template["dimension"],
        "question": template["question"],
        "options": list(template["options"]),
    }


def _tool_calls(query: str, intent: str, detected: dict[str, Any]) -> list[dict[str, Any]]:
    filters = {
        "query": query,
        "limit": 8,
        "public_only": detected.get("availability") == "public_only",
        "geography": detected.get("geography"),
        "time_range": detected.get("time_range"),
    }
    if intent == "compare_concepts":
        return [
            {
                "name": "compare_concepts_auto",
                "args": {
                    "query": query,
                    "geography": detected.get("geography"),
                    "public_only": detected.get("availability") == "public_only",
                },
            }
        ]
    if intent == "find_organizations":
        return [{"name": "semantic_search", "args": {"query": query, "object_types": ["organization"], "limit": 8}}]
    return [{"name": "find_data", "args": {key: value for key, value in filters.items() if value is not None}}]


def _inferred_query(query: str, inferred_bits: dict[str, str]) -> str:
    additions = [value for value in inferred_bits.values() if value and value.lower() not in query.lower()]
    if not additions:
        return query
    return ", ".join([query, *additions])


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _legacy_metric_type(metric_type: Any) -> Any:
    return {
        "funding_amount": "amount",
        "deal_count": "count",
        "stage_breakdown": "breakdown",
        "sector_breakdown": "breakdown",
        "percentage": "rate",
    }.get(metric_type, metric_type)
