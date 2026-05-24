from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


METRIC_TERMS = {
    "amount": ("amount", "funding", "investment", "capital", "expenditure", "spend", "value"),
    "count": ("count", "number", "deal count", "companies", "births"),
    "rate": ("rate", "percentage", "percent", "%", "intensity"),
    "share": ("share", "proportion"),
    "breakdown": ("by stage", "by sector", "by country", "breakdown", "segmentation"),
    "ranking": ("ranking", "rank", "top"),
    "definition": ("definition", "define", "definitions"),
    "source": ("source", "data source", "where from"),
    "organization": ("organization", "organisations", "association", "accelerator", "incubator", "agency", "directory"),
}
GEOGRAPHIES = (
    "Singapore",
    "Hong Kong",
    "Shenzhen",
    "China",
    "Asia",
    "Malaysia",
    "Indonesia",
    "Vietnam",
    "Thailand",
    "India",
    "Japan",
    "Korea",
)
COMPARISON_TERMS = ("compare", "differ", "different", "differences", "comparable", "definition differences")
ORG_TERMS = ("organization", "organizations", "organisation", "organisations", "association", "accelerator", "incubator", "agency", "directory", "ecosystem group")
BROAD_TERMS = ("startup data", "innovation data", "sme data", "what data", "data about", "tell me about")


@dataclass
class QueryPlan:
    intent: str
    ambiguity_level: str
    should_ask_clarifying_question: bool
    clarifying_questions: list[dict] = field(default_factory=list)
    extracted_filters: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def plan_query(query: str, context: dict | None = None) -> dict:
    text = (query or "").strip()
    lowered = text.lower()
    context = context or {}
    filters = {
        "geography": _detect_geography(text, context),
        "time_range": _detect_time_range(text),
        "public_only": "public" in lowered or bool((context.get("selected_filters") or {}).get("public_only")),
        "domain": _detect_domain(lowered),
        "preferred_metric_type": _detect_metric_type(lowered),
    }
    intent = _detect_intent(lowered)
    questions = _clarifying_questions(lowered, intent, filters)
    broad = _is_broad(lowered, intent, filters)
    ambiguity = "high" if broad and len(questions) >= 2 else "medium" if questions else "low"
    should_ask = broad or (intent == "unknown")
    if intent in {"compare_concepts", "find_organizations"} and text:
        should_ask = False
    if intent == "find_data" and filters["domain"] and filters["geography"] and filters["preferred_metric_type"]:
        should_ask = False
        ambiguity = "low"
    return QueryPlan(
        intent=intent,
        ambiguity_level=ambiguity,
        should_ask_clarifying_question=should_ask,
        clarifying_questions=questions,
        extracted_filters=filters,
    ).to_dict()


def _detect_intent(lowered: str) -> str:
    if any(term in lowered for term in COMPARISON_TERMS):
        return "compare_concepts"
    if any(term in lowered for term in ORG_TERMS):
        return "find_organizations"
    if "variable" in lowered or "definition of" in lowered:
        return "explain_variable"
    if any(term in lowered for term in BROAD_TERMS):
        return "broad_exploration"
    if lowered:
        return "find_data"
    return "unknown"


def _detect_metric_type(lowered: str) -> str | None:
    for metric_type, terms in METRIC_TERMS.items():
        if any(term in lowered for term in terms):
            return metric_type
    return None


def _detect_geography(query: str, context: dict) -> str | None:
    selected = (context.get("selected_filters") or {}).get("geography")
    if selected:
        return selected
    lowered = query.lower()
    for geography in GEOGRAPHIES:
        if geography.lower() in lowered:
            return geography
    return None


def _detect_time_range(query: str) -> str | None:
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    if not years:
        return None
    return "-".join([years[0], years[-1]]) if len(years) > 1 else years[0]


def _detect_domain(lowered: str) -> str | None:
    for domain in ("startup", "vc", "venture", "sme", "innovation", "r&d", "research", "digital adoption"):
        if domain in lowered:
            return domain
    return None


def _is_broad(lowered: str, intent: str, filters: dict) -> bool:
    if intent == "broad_exploration":
        return True
    if intent != "find_data":
        return False
    return bool(filters.get("domain")) and not filters.get("geography") and not filters.get("preferred_metric_type")


def _clarifying_questions(lowered: str, intent: str, filters: dict) -> list[dict]:
    if intent in {"compare_concepts", "find_organizations"}:
        return []
    questions = []
    if filters.get("domain") and not filters.get("geography"):
        questions.append(
            {
                "question": "Which market are you interested in?",
                "options": ["Singapore", "Hong Kong", "Shenzhen", "China", "Asia"],
            }
        )
    if filters.get("domain") and not filters.get("preferred_metric_type"):
        questions.append(
            {
                "question": "What kind of metric do you want?",
                "options": ["Funding amount", "Deal count", "Rate or share", "Stage breakdown", "Data source"],
            }
        )
    if not lowered:
        questions.append({"question": "What data question should I help with?", "options": []})
    return questions[:2]
