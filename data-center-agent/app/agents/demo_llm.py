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
You are writing the final response for a data discovery demo.

Use only the supplied tool results and normalized results. Do not invent reports, variables, organizations, URLs, evidence, numbers, or availability. If the results are weak or empty, say so plainly and ask a useful follow-up.

Write 2-5 concise sentences. Mention availability, evidence, and limitations when present. Do not include markdown tables.

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
