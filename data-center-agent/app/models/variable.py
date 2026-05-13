from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


DataSourceType = Literal["public_dataset", "private_database", "survey", "estimate", "report_table", "unknown"]
Availability = Literal["obtainable", "not_obtainable", "private", "unclear"]
ReviewStatus = Literal["pending_high_confidence", "pending", "needs_review"]


class Variable(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    canonical_name: str | None = None
    display_name: str | None = None
    concept_group: str | None = None
    description: str | None = None


class ReportVariable(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    report_id: UUID
    variable_id: UUID | None = None
    raw_variable_name: str
    definition: str | None = None
    measurement_method: str | None = None
    unit: str | None = None
    data_source_text: str | None = None
    data_source_type: str = "unknown"
    availability: str = "unclear"
    temporal_coverage: str | None = None
    geographic_coverage: str | None = None
    page_number: int | None = None
    evidence_chunk_id: UUID | None = None
    confidence_score: float | None = None
    review_status: str = "pending"
    metadata: dict | None = None


class ExtractedVariable(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: UUID
    variable_id: UUID | None = None
    raw_variable_name: str
    definition: str | None = None
    measurement_method: str | None = None
    unit: str | None = None
    data_source_text: str | None = None
    data_source_type: DataSourceType = "unknown"
    availability: Availability = "unclear"
    temporal_coverage: str | None = None
    geographic_coverage: str | None = None
    page_number: int | None = None
    evidence_chunk_id: UUID
    evidence_quote: str | None = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    review_status: ReviewStatus = "pending"
    metadata: dict = Field(default_factory=dict)


class CandidateChunk(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    report_id: UUID
    chunk_text: str
    page_number: int | None = None
    section_title: str | None = None
    chunk_type: str | None = None
    score: float
    reasons: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ExtractionVerificationResult(BaseModel):
    is_supported: bool
    evidence_quote_found: bool
    source_supported: bool
    temporal_supported: bool
    geographic_supported: bool
    warnings: list[str] = Field(default_factory=list)
    confidence_adjustment: float = 0.0
    metadata: dict = Field(default_factory=dict)


class VariableComparison(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    variable_a_id: UUID
    variable_b_id: UUID
    similarity_score: float | None = None
    same_name_different_definition: bool | None = None
    same_concept_different_measurement: bool | None = None
    difference_summary: str | None = None
    generated_by_model: str | None = None
    reviewed_by_human: bool = False
