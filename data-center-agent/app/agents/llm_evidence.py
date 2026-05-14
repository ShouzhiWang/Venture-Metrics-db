from typing import Any

from app.agents.codebook_extractor import _quote_supported
from app.models.llm_codebook import LLMExtractedItem


def verify_llm_item(item: LLMExtractedItem, chunks_by_id: dict[str, Any]) -> tuple[bool, str | None, float]:
    if item.item_type != "codebook_variable":
        return False, f"item_type:{item.item_type}", item.confidence_score
    if not item.keep_for_codebook:
        return False, "keep_for_codebook_false", item.confidence_score
    if not item.evidence_chunk_id or item.evidence_chunk_id not in chunks_by_id:
        return False, "missing_evidence_chunk_id", item.confidence_score
    if not item.evidence_quote:
        return False, "missing_evidence_quote", item.confidence_score

    chunk = chunks_by_id[item.evidence_chunk_id]
    text = chunk.get("chunk_text") if isinstance(chunk, dict) else getattr(chunk, "chunk_text", "")
    if not _quote_supported(item.evidence_quote, text or ""):
        return False, "evidence_quote_not_found", min(item.confidence_score, 0.55)

    score = item.confidence_score
    if not item.definition and not item.measurement_method:
        score = min(score, 0.65)
    return True, None, score
