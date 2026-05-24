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
    timeout_seconds: int | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        settings = get_settings()
        self.api_key = self.api_key if self.api_key is not None else settings.demo_llm_api_key
        self.base_url = self.base_url or settings.demo_llm_base_url
        self.model = self.model or settings.demo_llm_model
        self.timeout_seconds = self.timeout_seconds or settings.demo_llm_timeout_seconds
        self.max_output_tokens = self.max_output_tokens or settings.demo_llm_max_output_tokens
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
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=self.max_output_tokens,
            )
        except Exception as exc:  # pragma: no cover - provider classes vary.
            raise DemoLLMProviderError(f"Demo LLM provider request failed: {type(exc).__name__}") from exc
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise DemoLLMResponseError("Demo LLM returned an empty response.")
        return content


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
- For broad data queries, one useful search is allowed if the topic is clear; include follow-up questions in clarifying_questions.
- Never request ingestion, extraction, embedding jobs, deletion, migrations, shell commands, or filesystem access.

JSON shape:
{{
  "intent": "find_data",
  "ambiguity_level": "low|medium|high",
  "assistant_message": "short natural message or clarification",
  "clarifying_questions": [{{"question": "string", "options": ["optional"]}}],
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


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("json_object_not_found")
    return stripped[start : end + 1]
