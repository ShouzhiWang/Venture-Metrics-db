from typing import Literal

from pydantic import BaseModel, Field


ItemType = Literal[
    "codebook_variable",
    "chart_metric",
    "policy_category",
    "analytical_claim",
    "data_source_reference",
    "reject",
]
ReviewDecision = Literal[
    "valid_codebook_variable",
    "chart_metric_only",
    "policy_category",
    "analytical_claim",
    "source_reference",
    "reject",
]


class LLMExtractedItem(BaseModel):
    item_type: ItemType
    raw_variable_name: str | None = None
    definition: str | None = None
    measurement_method: str | None = None
    unit: str | None = None
    data_source_text: str | None = None
    data_source_type: str = "unknown"
    availability: str = "unclear"
    temporal_coverage: str | None = None
    geographic_coverage: str | None = None
    evidence_chunk_id: str | None = None
    evidence_quote: str | None = None
    keep_for_codebook: bool = False
    reason: str | None = None
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


class LLMExtractionResponse(BaseModel):
    items: list[LLMExtractedItem] = Field(default_factory=list)


class LLMReviewDecision(BaseModel):
    original_index: int
    review_decision: ReviewDecision
    keep_for_codebook: bool
    review_reason: str | None = None
    confidence_adjustment: float = 0.0


class LLMReviewResponse(BaseModel):
    reviewed_items: list[LLMReviewDecision] = Field(default_factory=list)
