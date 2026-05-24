from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EcosystemOrganization(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    name: str
    website_url: str | None = None
    description: str | None = None
    organization_type: str | None = None
    geography: str | None = None
    country: str | None = None
    city: str | None = None
    region: str | None = None
    sector_focus: list[str] | None = None
    stage_focus: list[str] | None = None
    market_focus: list[str] | None = None
    source_id: UUID | None = None
    original_source_url: str | None = None
    confidence_score: float | None = None
    review_status: str = "pending"
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
