from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
