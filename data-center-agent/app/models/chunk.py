from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentChunk(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    report_id: UUID
    chunk_text: str
    page_number: int | None = None
    section_title: str | None = None
    chunk_type: str = "unknown"
    token_count: int | None = None
    metadata: dict | None = None
