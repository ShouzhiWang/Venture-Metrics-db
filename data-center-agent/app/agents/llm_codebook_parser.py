import json
import re
from typing import Any

from pydantic import ValidationError

from app.models.llm_codebook import LLMExtractedItem, LLMExtractionResponse, LLMReviewDecision, LLMReviewResponse


class LLMParseError(ValueError):
    pass


def extract_json_from_response(raw_response: Any) -> dict[str, Any]:
    text = _response_text(raw_response)
    if not text:
        raise LLMParseError("empty_response_text")
    text = _strip_code_fence(text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise LLMParseError("json_object_not_found")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"invalid_json:{exc}") from exc


def parse_extraction_response(raw_response: Any) -> list[LLMExtractedItem]:
    try:
        payload = extract_json_from_response(raw_response)
        return LLMExtractionResponse.model_validate(payload).items
    except (LLMParseError, ValidationError) as exc:
        raise LLMParseError(str(exc)) from exc


def parse_review_response(raw_response: Any) -> list[LLMReviewDecision]:
    try:
        payload = extract_json_from_response(raw_response)
        return LLMReviewResponse.model_validate(payload).reviewed_items
    except (LLMParseError, ValidationError) as exc:
        raise LLMParseError(str(exc)) from exc


def _strip_code_fence(text: str) -> str:
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text


def _response_text(raw_response: Any) -> str:
    if isinstance(raw_response, str):
        return raw_response
    if not isinstance(raw_response, dict):
        return ""

    body = raw_response.get("response", {}).get("body") if isinstance(raw_response.get("response"), dict) else raw_response
    if not isinstance(body, dict):
        return ""

    if isinstance(body.get("output_text"), str):
        return body["output_text"]

    output = body.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            for content in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(content, dict):
                    if isinstance(content.get("text"), str):
                        parts.append(content["text"])
                    elif isinstance(content.get("json"), dict):
                        return json.dumps(content["json"])
        if parts:
            return "\n".join(parts)

    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))

    return ""
