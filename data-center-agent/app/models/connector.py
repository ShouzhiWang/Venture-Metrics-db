"""Pydantic models for the connector architecture tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ExternalSourceCandidate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    title: str | None = None
    url: str | None = None
    source_kind: str = "unknown"
    candidate_type: str | None = None
    geography: str | None = None
    ecosystem_category: str | None = None
    discovery_method: str | None = None
    confidence_score: float | None = None
    status: str = "pending_review"
    source_set: str | None = None
    raw_row_metadata: dict | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectorDataset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    name: str
    description: str | None = None
    publisher: str | None = None
    geography: str | None = None
    topic: str | None = None
    source_url: str | None = None
    portal: str | None = None
    license: str | None = None
    update_frequency: str | None = None
    last_modified_external: datetime | None = None
    access_type: str = "unknown"
    status: str = "discovered"
    source_candidate_id: UUID | None = None
    metadata: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectorResource(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    dataset_id: UUID
    resource_name: str | None = None
    resource_url: str | None = None
    format: str = "unknown"
    schema_metadata: dict | None = None
    local_path: str | None = None
    status: str = "pending"
    metadata: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectorSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    dataset_id: UUID
    resource_id: UUID | None = None
    retrieved_at: datetime | None = None
    query_params: dict | None = None
    row_count: int | None = None
    column_count: int | None = None
    local_path: str | None = None
    checksum: str | None = None
    schema_version: str | None = None
    status: str = "captured"
    metadata: dict | None = None
    created_at: datetime | None = None


class ConnectorRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    snapshot_id: UUID
    row_json: dict
    created_at: datetime | None = None
