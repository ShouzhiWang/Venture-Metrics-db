from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import get_settings


class DemoLLMConfigError(RuntimeError):
    """Raised when the demo LLM is not configured."""


class DemoLLMResponseError(RuntimeError):
    """Raised when the demo LLM returns unusable output."""


class DemoLLMProviderError(RuntimeError):
    """Raised when the provider request fails."""


@dataclass
class DemoLLMClient:
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    provider: str | None = None
    timeout_seconds: int | None = None
    max_output_tokens: int | None = None
    thinking: str | None = None

    def __post_init__(self) -> None:
        settings = get_settings()
        self.api_key = self.api_key if self.api_key is not None else settings.demo_llm_api_key
        self.base_url = self.base_url or settings.demo_llm_base_url
        self.model = self.model or settings.demo_llm_model
        self.provider = self.provider or settings.demo_llm_provider
        self.timeout_seconds = self.timeout_seconds or settings.demo_llm_timeout_seconds
        self.max_output_tokens = self.max_output_tokens or settings.demo_llm_max_output_tokens
        self.thinking = self.thinking if self.thinking is not None else settings.demo_llm_thinking
        if not self.api_key:
            raise DemoLLMConfigError("Demo LLM is not configured. Set DEMO_LLM_API_KEY for the web API.")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise DemoLLMConfigError("The openai package is required for the MiMo-compatible demo LLM client.") from exc
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_seconds)

    def plan(self, *, message: str, history: list[dict[str, str]], safe_tools: set[str]) -> dict[str, Any]:
        prompt = _planner_prompt(message=message, history=history, safe_tools=safe_tools)
        return self._json_completion(prompt)

    def synthesize(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        plan: dict[str, Any],
        tool_results: list[dict[str, Any]],
        normalized_results: dict[str, Any],
        limitations: list[str],
    ) -> str:
        prompt = _synthesis_prompt(
            message=message,
            history=history,
            plan=plan,
            tool_results=tool_results,
            normalized_results=normalized_results,
            limitations=limitations,
        )
        return self._text_completion(prompt).strip()

    def qualify_evidence(
        self,
        *,
        evidence_packet: dict[str, Any],
    ) -> dict[str, Any]:
        """Classify each evidence item's relevance to the user query.

        Returns structured JSON with per-item classifications and an overall
        answer_support_level.  This runs BEFORE synthesis so the synthesizer
        can rely on pre-screened evidence.
        """
        prompt = _evidence_qualification_prompt(evidence_packet=evidence_packet)
        return self._json_completion(prompt)

    def synthesize_structured(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        plan: dict[str, Any],
        evidence_packet: dict[str, Any],
        limitations: list[str],
        evidence_qualification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Two-step structured synthesis: assess evidence relevance, then produce JSON answer."""
        prompt = _structured_synthesis_prompt(
            message=message,
            history=history,
            plan=plan,
            evidence_packet=evidence_packet,
            limitations=limitations,
            evidence_qualification=evidence_qualification,
        )
        return self._json_completion(prompt)

    def synthesize_no_results(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        plan: dict[str, Any],
        tool_results: list[dict[str, Any]],
        normalized_results: dict[str, Any],
        limitations: list[str],
    ) -> dict[str, Any]:
        prompt = _no_results_synthesis_prompt(
            message=message,
            history=history,
            plan=plan,
            tool_results=tool_results,
            normalized_results=normalized_results,
            limitations=limitations,
        )
        return self._json_completion(prompt)

    def synthesize_research_task(
        self,
        *,
        evidence_packet: dict[str, Any],
        comparability: dict[str, Any] | None = None,
    ) -> str:
        prompt = _research_task_synthesis_prompt(
            evidence_packet=evidence_packet,
            comparability=comparability or {},
        )
        return self._text_completion(prompt).strip()

    def _json_completion(self, prompt: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            text = self._text_completion(prompt if attempt == 0 else f"{prompt}\n\nReturn valid JSON only. No prose.")
            try:
                parsed = json.loads(_extract_json_object(text))
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
            last_error = DemoLLMResponseError("Planner JSON must be an object.")
        raise DemoLLMResponseError(f"Demo LLM returned invalid JSON: {last_error}")

    def _text_completion(self, prompt: str) -> str:
        attempts = [
            (prompt, int(self.max_output_tokens or 900)),
            (
                (
                    "Return the final answer in message.content. Keep any reasoning brief. "
                    "Do not leave message.content empty.\n\n"
                    f"{prompt}"
                ),
                max(int(self.max_output_tokens or 900) * 3, 2400),
            ),
        ]
        empty_detail = "empty response"
        for attempt_prompt, token_budget in attempts:
            content, empty_detail = self._request_text_completion(attempt_prompt, token_budget)
            if content:
                return content
        raise DemoLLMResponseError(f"Demo LLM returned an empty response ({empty_detail}).")

    def _request_text_completion(self, prompt: str, token_budget: int) -> tuple[str | None, str]:
        request_args: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_completion_tokens": token_budget,
        }
        extra_body = self._provider_extra_body()
        if extra_body:
            request_args["extra_body"] = extra_body
        try:
            response = self._client.chat.completions.create(**request_args)
        except Exception as exc:  # pragma: no cover - provider classes vary.
            raise DemoLLMProviderError(f"Demo LLM provider request failed: {type(exc).__name__}") from exc
        if not response.choices:
            return None, "no choices"
        choice = response.choices[0]
        content = choice.message.content
        if content:
            return content, ""
        reasoning = getattr(choice.message, "reasoning_content", None)
        finish_reason = getattr(choice, "finish_reason", None)
        detail = f"finish_reason={finish_reason or 'unknown'}, reasoning_tokens_or_chars={len(reasoning or '')}"
        return None, detail

    def _provider_extra_body(self) -> dict[str, Any]:
        thinking = (self.thinking or "").strip().lower()
        if not thinking:
            return {}
        provider_hint = f"{self.provider or ''} {self.base_url or ''} {self.model or ''}".lower()
        if not any(token in provider_hint for token in ("mimo", "xiaomi")):
            return {}
        if thinking not in {"enabled", "disabled", "auto"}:
            return {}
        return {"thinking": {"type": thinking}}


def _planner_prompt(*, message: str, history: list[dict[str, str]], safe_tools: set[str]) -> str:
    tool_names = sorted(name for name in safe_tools if name != "submit_feedback")
    return f"""
You are planning tool use for a public demo data assistant.

Return one JSON object only. Do not answer the user from memory.

Allowed tool names:
{json.dumps(tool_names)}

Intent values:
find_data, compare_concepts, find_organizations, explain_variable, broad_exploration, unknown

Rules:
- Use tools only from the allowed list.
- Prefer find_data for variables, metrics, reports, sources, availability, geography, or time coverage.
- Prefer compare_concepts_auto for comparison, comparability, definition differences, and "how do reports define" questions.
- Prefer semantic_search with object_types ["organization"] for organizations, associations, accelerators, incubators, agencies, directories, or ecosystem groups.
- Ask clarifying questions when the query is too broad to run a useful search.
- For high ambiguity, return no tool_calls and generate clarification_ui. Do not search first.
- For broad data queries, one useful search is allowed if the topic is clear; include follow-up questions in clarifying_questions.
- Never request ingestion, extraction, embedding jobs, deletion, migrations, shell commands, or filesystem access.
- clarification_ui.choice_options labels must be short human labels, not full rewritten queries.
- Use optional_fields for free-form inputs such as country/region, university, time period, output format, and availability.

JSON shape:
{{
  "intent": "find_data",
  "ambiguity_level": "low|medium|high",
  "assistant_message": "short natural message or clarification",
  "clarifying_questions": [{{"question": "string", "options": ["optional"]}}],
  "clarification_ui": {{
    "main_question": "focused question",
    "choice_options": [{{"label": "Short label", "value": "semantic choice value"}}],
    "optional_fields": [
      {{"name": "geography", "label": "Country/region", "type": "text", "placeholder": "e.g. Hong Kong, Singapore, China"}},
      {{"name": "university", "label": "University", "type": "text", "placeholder": "e.g. HKUST, NUS, Tsinghua"}},
      {{"name": "time_period", "label": "Time period", "type": "text_or_chips", "options": ["Last 3 years", "Last 5 years", "Since 2020"]}},
      {{"name": "output_format", "label": "Output", "type": "single_select", "options": ["Answer", "Table", "Excel", "Source list"]}}
    ],
    "suggested_searches": [{{"label": "Broader overview", "query_append": "broader overview, key metrics and trends"}}],
    "defaults": {{"label": "Run with defaults", "choice": "Broad overview", "fields": {{"time_period": "Last 5 years", "output_format": "Answer"}}}}
  }},
  "tool_calls": [{{"name": "find_data", "args": {{"query": "user query", "limit": 8, "public_only": false}}}}],
  "filters": {{"geography": null, "time_range": null, "public_only": false}}
}}

Recent conversation:
{json.dumps(history[-8:], ensure_ascii=True)}

User message:
{message}
""".strip()


def _synthesis_prompt(
    *,
    message: str,
    history: list[dict[str, str]],
    plan: dict[str, Any],
    tool_results: list[dict[str, Any]],
    normalized_results: dict[str, Any],
    limitations: list[str],
) -> str:
    return f"""
You are a research data assistant. Your job is to ANSWER the user's question using the search results below.

## Response rules

1. **Lead with the answer, not the search.** Start with what you found — specific indicators, metrics, datasets, organizations, or trends relevant to the question. Do NOT start with "the search found" or "results were limited."
2. **Be substantive.** Name specific datasets, indicators, organizations, and data portals. Mention what data is actually available (e.g. "the Intellectual Property Department publishes monthly trademark filing counts" rather than "there are some relevant sources").
3. **Synthesize across sources.** If multiple sources are relevant, combine them into a coherent picture. Don't list sources one by one.
4. **Be honest about gaps.** If specific data points (numbers, trends) aren't in the results, say what IS available and suggest how to get the rest.
5. **Never say "limited results."** Instead, describe what you found and what the next step would be.
6. **Keep it to 3-6 sentences.** No markdown tables. No bullet-point source lists.

Do not invent numbers, statistics, or URLs that aren't in the results. But DO use the metadata (titles, descriptions, portals, organizations) to give a real answer.

Recent conversation:
{json.dumps(history[-8:], ensure_ascii=True)}

User message:
{message}

Planner output:
{json.dumps(plan, ensure_ascii=True, default=str)}

Normalized results:
{json.dumps(normalized_results, ensure_ascii=True, default=str)[:12000]}

Tool results:
{json.dumps(tool_results, ensure_ascii=True, default=str)[:16000]}

Limitations:
{json.dumps(limitations, ensure_ascii=True)}
""".strip()


def _evidence_qualification_prompt(*, evidence_packet: dict[str, Any]) -> str:
    """Build prompt for LLM evidence qualification step.

    Classifies each retrieved item as direct/partial/contextual/misleading
    evidence for the user's query.  Runs before synthesis.
    """
    return f"""
You are an evidence qualification step in a research data pipeline.

Given a user query and a set of retrieved evidence items, classify EVERY item.

## Classification definitions

**direct_evidence**: Matches the requested metric/concept, geography, time period,
AND any sector/topic filter closely enough to support the main answer.

**partial_evidence**: Matches some dimensions but misses one or more of:
exact year range, sector/technology filter, geography, or metric definition.

**contextual_evidence**: Useful background but not enough to support the
requested claim directly.

**misleading_or_irrelevant**: Would mislead the user if used as evidence
for this query (e.g. aggregate data presented as sector-specific, proxy
data that does not measure the requested concept).

## Sector/topic filter rule (CRITICAL)

If the user query contains a sector, technology, subtopic, or entity filter
(clean energy, fintech, AI, biotech, semiconductors, climate tech, university,
spin-off, startup exits, sector-specific funding, etc.), the evidence MUST
explicitly support that filter to be classified as direct_evidence.

Evidence supports a filter when the filter term appears in:
- dataset column name, row value, variable name, report section/title,
  evidence quote, source title/description, extracted text, external source
  snippet, or computed finding.

If the filter is ABSENT from the evidence, classify as partial or contextual —
NOT direct.  This is a general rule, not query-specific.

## Proxy data rule

Do NOT classify loosely related proxy data as direct_evidence:
- net capital stock ≠ VC funding
- school enrolment ≠ startup funding
- generic VC funding ≠ fintech funding (unless "fintech" appears in evidence)
- aggregate patent totals ≠ clean-energy patent trends (unless clean-energy
  classification is present in evidence)
- GDP ≠ startup funding (unless explicitly used as macro context)

## Output schema

Return one JSON object:

{{
  "evidence_items": [
    {{
      "id": "<id from evidence packet>",
      "classification": "direct_evidence | partial_evidence | contextual_evidence | misleading_or_irrelevant",
      "reason": "<1-2 sentence explanation>",
      "matched_dimensions": {{
        "metric_or_concept": true/false,
        "geography": true/false,
        "time_period": true/false,
        "sector_or_topic": true/false,
        "organization": true/false,
        "unit": true/false
      }},
      "can_support_main_answer": true/false
    }}
  ],
  "answer_support_level": "strong | partial | contextual_only | unresolved",
  "missing_dimensions": ["<list of dimensions with no direct evidence>"],
  "safe_answer_strategy": "direct_answer | partial_answer | directional_answer | source_discovery_needed | unresolved_explanation"
}}

answer_support_level rules:
- strong: ≥1 direct_evidence item with can_support_main_answer=true
- partial: ≥1 partial_evidence item, 0 direct
- contextual_only: only contextual_evidence found
- unresolved: only misleading_or_irrelevant or no items

## Context

Evidence packet:
{json.dumps(evidence_packet, ensure_ascii=True, default=str)[:16000]}
""".strip()


def _structured_synthesis_prompt(
    *,
    message: str,
    history: list[dict[str, str]],
    plan: dict[str, Any],
    evidence_packet: dict[str, Any],
    limitations: list[str],
    evidence_qualification: dict[str, Any] | None = None,
) -> str:
    qual_section = ""
    if evidence_qualification:
        qual_section = f"""

## Evidence Qualification (pre-screened)

The following classification has already been performed.  You MUST respect it:
- Do NOT use items classified as "misleading_or_irrelevant" in your main answer.
- Items classified as "contextual_evidence" may be mentioned as background
  but MUST NOT be the primary support for a numeric claim.
- Items classified as "direct_evidence" are the strongest support.
- Items classified as "partial_evidence" can support a partial answer —
  clearly state what they measure vs what remains unresolved.

answer_support_level: {evidence_qualification.get("answer_support_level", "unknown")}
safe_answer_strategy: {evidence_qualification.get("safe_answer_strategy", "unknown")}
missing_dimensions: {json.dumps(evidence_qualification.get("missing_dimensions", []))}

Per-item classifications:
{json.dumps(evidence_qualification.get("evidence_items", []), ensure_ascii=True, default=str)[:8000]}
"""

    return f"""
You are a research data assistant that produces structured, evidence-based answers.

## STEP 1: Use the evidence qualification

Read the pre-screened evidence classification below.  You MUST NOT use
misleading_or_irrelevant items as primary evidence.

## STEP 2: Sector/topic guardrail

If the user query contains a sector, technology, subtopic, or entity filter,
your answer MUST NOT present aggregate or unfiltered data as if it were
specific to that filter — unless the filter term explicitly appears in the
evidence itself (column name, row value, variable name, report title,
evidence quote, or computed finding).

For example:
- If the user asks for "clean energy patent trends" and the evidence only
  contains aggregate patent totals without a clean-energy classification,
  the answer must say the evidence covers total patents, not clean-energy patents.
- If the user asks for "fintech funding" and the evidence only contains
  generic VC funding without "fintech" appearing in the source,
  the answer must say the evidence covers general VC funding, not fintech specifically.

## STEP 3: Proxy data ban

Do NOT use loosely related proxy data as the main answer:
- net capital stock is not VC funding
- school enrolment is not startup funding
- generic VC funding is not fintech funding (unless fintech is in the evidence)
- aggregate patent totals are not clean-energy patent trends (unless clean-energy
  classification is present)
- generic organization pages are not numeric market trend evidence
- GDP is not startup funding (unless explicitly used as macro context)

## STEP 4: Negative phrasing ban

NEVER start the answer with:
- "Currently, there is no available data..."
- "I do not currently have..."
- "The database has limited matches..."
- "I couldn't find anything..."
- "Consider checking..."

Instead, lead with one of:
- "The strongest supported answer is..."
- "The best available evidence indicates..."
- "The clearest finding is..."
- "The available evidence supports a partial answer..."
- "Exact figures are unresolved because..."

Sound like a research analyst, not a database status report.

## STEP 5: Write the answer based on support level

If answer_support_level = strong:
  → answer directly with values/table if available, cite sources

If answer_support_level = partial:
  → give the strongest supported partial answer
  → clearly say what the evidence measures
  → clearly say what remains unresolved

If answer_support_level = contextual_only:
  → give a directional or contextual answer only
  → do NOT present context as exact data
  → explain what source/data would be needed

If answer_support_level = unresolved:
  → explain why reliable sources did not support an answer
  → provide source-discovery or ingestion next steps

## STEP 6: When table values are present

When table_values_read items are present, you MUST use the actual computed
values (rows_sample, aggregations, time_series) as your primary evidence.
Cite specific numbers.  Do not ignore actual data in favor of metadata-only sources.

## STEP 7: Return structured JSON

Return one JSON object with this exact schema:

{{
  "answer_evidence_level": "table_values_read | exact_internal | partial_internal | synced_connector | text_evidence_read | external_verified | external_candidate | directional_only | unresolved_after_search",
  "support_level": "strong | partial | contextual_only | unresolved",
  "direct_answer": "The main answer in 1-2 sentences",
  "main_claims": [
    {{
      "claim": "Specific factual claim",
      "evidence_ids": ["id from evidence packet"],
      "confidence": "high | medium | low"
    }}
  ],
  "what_evidence_measures": [
    "Each item: what the evidence actually measures (e.g. 'total patent applications, not sector-specific')"
  ],
  "what_is_not_supported": [
    "Each item: what the evidence does NOT support (e.g. 'clean-energy-specific trends')"
  ],
  "data_needed": [
    "Each item: specific data that would fill the gap"
  ],
  "evidence_used": [
    {{
      "id": "id from evidence packet",
      "usage": "direct | partial | contextual",
      "reason": "Why this item is relevant"
    }}
  ],
  "evidence_excluded": [
    {{
      "id": "id from evidence packet",
      "reason": "Why this item was excluded"
    }}
  ],
  "methodology_caveats": ["Caveat about sources, definitions, comparability..."],
  "missing_data": ["What data was not found"],
  "recommended_next_actions": [
    {{
      "label": "Short action label",
      "action_type": "ingest_source | run_external_discovery | create_excel | compare_definitions | broaden_search | narrow_search",
      "details": "Specific details about this action"
    }}
  ],
  "final_answer_markdown": "The full answer as markdown for display. 3-6 sentences. Must follow the style rules above."
}}

## Context

Recent conversation:
{json.dumps(history[-8:], ensure_ascii=True)}

User message:
{message}

Planner output:
{json.dumps(plan, ensure_ascii=True, default=str)}

Evidence packet:
{json.dumps(evidence_packet, ensure_ascii=True, default=str)[:14000]}
{qual_section}
Limitations:
{json.dumps(limitations, ensure_ascii=True)}
""".strip()


def _no_results_synthesis_prompt(
    *,
    message: str,
    history: list[dict[str, str]],
    plan: dict[str, Any],
    tool_results: list[dict[str, Any]],
    normalized_results: dict[str, Any],
    limitations: list[str],
) -> str:
    return f"""
You are writing the final response for a data discovery demo when a search returned no strong structured matches.

Use only the supplied context. Do not invent reports, variables, organizations, URLs, evidence, numbers, or availability.

Return one JSON object only with this shape:
{{
  "assistant_message": "2-4 concise sentences explaining what was searched and what to try next",
  "follow_up_queries": [
    {{"label": "Short chip label (3-6 words)", "query": "A complete follow-up search the user can run"}},
    ...
  ]
}}

Rules for follow_up_queries:
- Provide 3 or 4 items.
- Each query must be a realistic next search in plain English (metric, geography, source type, organization type, or related concept).
- Do not repeat the exact same wording as the user message unless narrowing it.
- Labels should be short; queries can be longer and specific.
- Do not invent dataset names or URLs.

Recent conversation:
{json.dumps(history[-8:], ensure_ascii=True)}

User message:
{message}

Planner output:
{json.dumps(plan, ensure_ascii=True, default=str)}

Normalized results:
{json.dumps(normalized_results, ensure_ascii=True, default=str)[:8000]}

Tool results:
{json.dumps(tool_results, ensure_ascii=True, default=str)[:8000]}

Limitations:
{json.dumps(limitations, ensure_ascii=True)}
""".strip()


def _research_task_synthesis_prompt(*, evidence_packet: dict[str, Any], comparability: dict[str, Any]) -> str:
    return f"""
You are writing a research-ready answer from a structured evidence packet.

Use only the evidence packet and comparability result below. Do not invent reports, source names, URLs, metrics, values, units, years, availability labels, or organizations. If a value is missing or value_status is "not_extracted", say that the current evidence does not expose a numeric value.

Required answer structure:
1. Start with a direct answer to the user's request.
2. Distinguish direct matches from contextual matches.
3. Group related variables into concepts.
4. Discuss values, units, years, geography, and dimensions only when present in the packet.
5. Cite report/source names and source URLs when present.
6. Label public/private/unclear/obtainable availability.
7. Explain limitations specifically.
8. If aggregation is blocked, explain each blocker and what metadata would be needed to aggregate safely. Do not perform arithmetic unless comparability.can_aggregate is true.
9. Suggest next actions only after the answer and limitations.

Keep the answer concise but useful. Markdown bullets are allowed. Do not include a large raw JSON dump.

Evidence packet:
{json.dumps(evidence_packet, ensure_ascii=True, default=str)[:22000]}

Comparability:
{json.dumps(comparability, ensure_ascii=True, default=str)[:8000]}
""".strip()


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("json_object_not_found")
    return stripped[start : end + 1]
