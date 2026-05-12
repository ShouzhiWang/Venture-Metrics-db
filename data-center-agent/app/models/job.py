from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IngestionJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    job_type: str
    status: str = "pending"
    source_id: UUID | None = None
    report_id: UUID | None = None
    input_payload: dict | None = None
    output_payload: dict | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
