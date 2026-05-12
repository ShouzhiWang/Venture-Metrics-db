from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Report(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    source_id: UUID | None = None
    title: str | None = None
    publisher: str | None = None
    publication_date: date | None = None
    report_year: int | None = None
    geography: str | None = None
    language: str | None = None
    summary: str | None = None
    raw_text_path: str | None = None
    parsed_json_path: str | None = None
    citation_info: dict | None = None
