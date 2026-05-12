from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Dataset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    source_id: UUID
    report_id: UUID | None = None
    dataset_name: str | None = None
    data_origin_type: str = "unknown"
    temporal_coverage_start: date | None = None
    temporal_coverage_end: date | None = None
    geography_coverage: str | None = None
    license_or_access_note: str | None = None
    raw_data_path: str | None = None
    metadata: dict | None = None
