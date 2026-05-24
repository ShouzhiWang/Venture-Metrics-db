from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SearchIndexItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    object_type: str
    object_id: UUID
    title: str | None = None
    content: str
    search_text: str
    source_id: UUID | None = None
    report_id: UUID | None = None
    variable_id: UUID | None = None
    dataset_id: UUID | None = None
    chunk_id: UUID | None = None
    geography: str | None = None
    time_coverage: str | None = None
    availability: str = "unclear"
    source_url: str | None = None
    local_path: str | None = None
    evidence_quote: str | None = None
    rank_weight: float = 1.0
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    embedding_normalized: bool = True
    embedding_status: str = "pending"
    metadata: dict = Field(default_factory=dict)


class SearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    object_type: str
    object_id: UUID
    score: float = 0.0
    title: str | None = None
    snippet: str | None = None
    content: str | None = None
    search_text: str | None = None
    source_id: UUID | None = None
    report_id: UUID | None = None
    variable_id: UUID | None = None
    dataset_id: UUID | None = None
    chunk_id: UUID | None = None
    geography: str | None = None
    time_coverage: str | None = None
    availability: str = "unclear"
    source_url: str | None = None
    local_path: str | None = None
    evidence_quote: str | None = None
    metadata: dict = Field(default_factory=dict)


class SuggestedClarification(BaseModel):
    question: str
    reason: str


class FindDataResult(BaseModel):
    query: str
    parsed_intent: dict = Field(default_factory=dict)
    closest_variables: list[dict] = Field(default_factory=list)
    closest_datasets: list[dict] = Field(default_factory=list)
    relevant_reports: list[dict] = Field(default_factory=list)
    source_links: list[dict] = Field(default_factory=list)
    suggested_clarifications: list[SuggestedClarification] = Field(default_factory=list)
    search_mode: str = "hybrid"
    warning: str | None = None
