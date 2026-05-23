from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Source(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    original_url: str | None = None
    source_type: str = "unknown"
    source_owner: str | None = None
    access_type: str = "unknown"
    detected_format: str | None = None
    title: str | None = None
    crawl_status: str = "pending"
    raw_file_path: str | None = None
    raw_file_sha256: str | None = None
    mime_type: str | None = None
    last_checked_at: datetime | None = None
    notes: str | None = None
    parent_source_id: UUID | None = None
    source_role: str | None = None
    resolution_status: str | None = None
    resolved_source_id: UUID | None = None
    resolution_notes: str | None = None
    discovered_artifacts: list[dict] | dict | None = None
