"""SourceConnector base interface and implementations.

Each connector handles a specific source_kind or data type.
Connectors follow the discover → sync → query lifecycle.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd

from app.config import get_settings

logger = logging.getLogger(__name__)


class ConnectorResult:
    """Unified result from connector operations."""

    def __init__(
        self,
        *,
        success: bool = True,
        dataset_meta: dict[str, Any] | None = None,
        resource_meta: dict[str, Any] | None = None,
        snapshot_meta: dict[str, Any] | None = None,
        rows: list[dict] | None = None,
        local_path: str | None = None,
        error: str | None = None,
        needs_connector: bool = False,
    ):
        self.success = success
        self.dataset_meta = dataset_meta or {}
        self.resource_meta = resource_meta or {}
        self.snapshot_meta = snapshot_meta or {}
        self.rows = rows
        self.local_path = local_path
        self.error = error
        self.needs_connector = needs_connector


class SourceConnector(ABC):
    """Base class for all source connectors."""

    @abstractmethod
    def can_handle(self, candidate: dict[str, Any]) -> bool:
        """Return True if this connector can handle the candidate."""
        ...

    @abstractmethod
    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Lightweight inspection — return metadata without downloading."""
        ...

    @abstractmethod
    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        """Discover and classify the candidate. Return metadata only."""
        ...

    @abstractmethod
    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        """Download/sync the resource. Return snapshot result."""
        ...

    def query(self, dataset_or_resource: dict[str, Any], params: dict | None = None) -> ConnectorResult:
        """Query external API (only when cache missing/stale). Override for API connectors."""
        return ConnectorResult(success=False, error="Query not supported for this connector type")

    def normalize(self, raw_result: Any) -> dict[str, Any]:
        """Normalize raw result into standard metadata. Override as needed."""
        return {}


class GenericDownloadableFileConnector(SourceConnector):
    """Handles direct CSV/XLSX file downloads."""

    SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls"}

    def can_handle(self, candidate: dict[str, Any]) -> bool:
        kind = candidate.get("source_kind", "")
        return kind in ("downloadable_csv", "downloadable_xlsx")

    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        url = candidate.get("url", "")
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        return {
            "format": "csv" if ext in (".csv", ".tsv") else "xlsx",
            "url": url,
            "domain": parsed.netloc,
        }

    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        meta = self.inspect(candidate)
        url = candidate.get("url", "")
        name = candidate.get("title") or _filename_from_url(url)

        return ConnectorResult(
            dataset_meta={
                "name": name,
                "source_url": url,
                "access_type": meta["format"],
                "geography": candidate.get("geography"),
                "description": candidate.get("raw_row_metadata", {}).get("用途 / 数据内容", ""),
                "portal": urlparse(url).netloc,
            },
            resource_meta={
                "resource_name": name,
                "resource_url": url,
                "format": meta["format"],
            },
        )

    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        url = candidate_or_resource.get("resource_url") or candidate_or_resource.get("url", "")
        if not url:
            return ConnectorResult(success=False, error="No URL to download")

        settings = get_settings()
        storage_root = settings.storage_root

        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return ConnectorResult(success=False, error=f"Download failed: {exc}")

        content = resp.content
        checksum = hashlib.sha256(content).hexdigest()
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower() or ".bin"
        filename = _filename_from_url(url) + ext

        # Save to storage
        connector_dir = storage_root / "connector_downloads"
        connector_dir.mkdir(parents=True, exist_ok=True)
        local_path = connector_dir / f"{checksum[:12]}_{filename}"
        local_path.write_bytes(content)

        # Parse to get row/column counts
        rows = []
        row_count = 0
        col_count = 0
        columns = []
        try:
            if ext in (".csv", ".tsv"):
                sep = "\t" if ext == ".tsv" else ","
                df = pd.read_csv(io.BytesIO(content), sep=sep, nrows=limit)
            else:
                df = pd.read_excel(io.BytesIO(content), nrows=limit)
            row_count = len(df)
            col_count = len(df.columns)
            columns = list(df.columns)
            rows = df.head(limit).to_dict(orient="records")
        except Exception as exc:
            logger.warning("Failed to parse downloaded file: %s", exc)

        format_type = "csv" if ext in (".csv", ".tsv") else "xlsx"

        return ConnectorResult(
            dataset_meta={
                "name": _filename_from_url(url),
                "source_url": url,
                "access_type": format_type,
            },
            resource_meta={
                "resource_name": _filename_from_url(url),
                "resource_url": url,
                "format": format_type,
                "schema_metadata": {"columns": columns},
                "local_path": str(local_path),
                "status": "downloaded",
            },
            snapshot_meta={
                "row_count": row_count,
                "column_count": col_count,
                "local_path": str(local_path),
                "checksum": checksum,
                "status": "captured",
                "metadata": {"columns": columns, "format": format_type},
            },
            rows=rows,
            local_path=str(local_path),
        )


class GenericHTMLTableConnector(SourceConnector):
    """Handles simple pages with visible HTML tables."""

    def can_handle(self, candidate: dict[str, Any]) -> bool:
        return candidate.get("source_kind") == "html_table"

    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {"format": "html_table", "url": candidate.get("url", "")}

    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        url = candidate.get("url", "")
        return ConnectorResult(
            dataset_meta={
                "name": candidate.get("title") or _filename_from_url(url),
                "source_url": url,
                "access_type": "html_table",
                "geography": candidate.get("geography"),
            },
            resource_meta={
                "resource_name": "HTML Table",
                "resource_url": url,
                "format": "html",
            },
        )

    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        url = candidate_or_resource.get("resource_url") or candidate_or_resource.get("url", "")
        if not url:
            return ConnectorResult(success=False, error="No URL")

        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return ConnectorResult(success=False, error=f"Fetch failed: {exc}")

        try:
            tables = pd.read_html(io.StringIO(resp.text))
        except Exception as exc:
            return ConnectorResult(success=False, error=f"No HTML tables found: {exc}")

        if not tables:
            return ConnectorResult(success=False, error="No tables found on page")

        # Take the largest table
        df = max(tables, key=len)
        df = df.head(limit)
        rows = df.to_dict(orient="records")
        columns = list(df.columns)

        checksum = hashlib.sha256(resp.content).hexdigest()

        return ConnectorResult(
            snapshot_meta={
                "row_count": len(df),
                "column_count": len(df.columns),
                "checksum": checksum,
                "status": "captured",
                "metadata": {"columns": columns},
            },
            rows=rows,
        )


class GenericOrganizationPageConnector(SourceConnector):
    """Handles TTO/incubator/organization pages.
    Creates ecosystem_organizations records — NOT report/codebook entries.
    """

    def can_handle(self, candidate: dict[str, Any]) -> bool:
        return candidate.get("source_kind") == "organization_page"

    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {"type": "organization_page", "url": candidate.get("url", "")}

    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        meta = candidate.get("raw_row_metadata", {})
        return ConnectorResult(
            dataset_meta={
                "name": candidate.get("title", ""),
                "source_url": candidate.get("url", ""),
                "access_type": "portal",
                "geography": candidate.get("geography", "Hong Kong"),
                "description": meta.get("名称 / 说明", ""),
            },
        )

    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        # Organization pages don't produce data snapshots — they become org records
        return ConnectorResult(
            success=True,
            dataset_meta={"name": candidate_or_resource.get("title", "")},
            needs_connector=False,
        )


class GenericPDFReportCandidateConnector(SourceConnector):
    """Handles direct PDF links. Creates source candidates — does NOT auto-extract."""

    def can_handle(self, candidate: dict[str, Any]) -> bool:
        return candidate.get("source_kind") == "downloadable_pdf"

    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {"type": "pdf", "url": candidate.get("url", "")}

    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        return ConnectorResult(
            dataset_meta={
                "name": candidate.get("title") or _filename_from_url(candidate.get("url", "")),
                "source_url": candidate.get("url", ""),
                "access_type": "manual",
                "geography": candidate.get("geography"),
            },
        )

    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        # PDFs are NOT auto-synced — they need approval for codebook extraction
        return ConnectorResult(
            success=True,
            needs_connector=True,
            dataset_meta={"name": candidate_or_resource.get("title", "PDF")},
        )


class DataGovHKConnector(SourceConnector):
    """Handles data.gov.hk URLs — metadata discovery and resource sync."""

    def can_handle(self, candidate: dict[str, Any]) -> bool:
        url = (candidate.get("url") or "").lower()
        return "data.gov.hk" in url

    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {"type": "data_gov_hk", "url": candidate.get("url", "")}

    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        url = candidate.get("url", "")
        # Try to extract dataset ID from data.gov.hk URL
        dataset_id = _extract_data_gov_hk_id(url)

        return ConnectorResult(
            dataset_meta={
                "name": candidate.get("title") or "Data.gov.hk Dataset",
                "source_url": url,
                "access_type": "api",
                "geography": "Hong Kong",
                "portal": "data.gov.hk",
                "description": candidate.get("raw_row_metadata", {}).get("用途 / 数据内容", ""),
                "metadata": {"data_gov_hk_id": dataset_id} if dataset_id else {},
            },
            resource_meta={
                "resource_name": "Data.gov.hk API",
                "resource_url": url,
                "format": "api",
            },
        )

    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        url = candidate_or_resource.get("resource_url") or candidate_or_resource.get("url", "")
        dataset_id = _extract_data_gov_hk_id(url)

        if not dataset_id:
            return ConnectorResult(
                success=False,
                error="Cannot extract dataset ID from data.gov.hk URL",
                needs_connector=True,
            )

        # Try the data.gov.hk datastore API
        api_url = f"https://data.gov.hk/en-data/dataset/{dataset_id}"
        meta_api = f"https://data.gov.hk/en/api/3/action/package_show?id={dataset_id}"

        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.get(meta_api)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        pkg = data.get("result", {})
                        resources = pkg.get("resources", [])
                        return ConnectorResult(
                            dataset_meta={
                                "name": pkg.get("title", dataset_id),
                                "description": pkg.get("notes", ""),
                                "source_url": api_url,
                                "access_type": "api",
                                "geography": "Hong Kong",
                                "portal": "data.gov.hk",
                                "metadata": {
                                    "data_gov_hk_id": dataset_id,
                                    "resources": resources[:5],
                                    "license": pkg.get("license_id"),
                                },
                            },
                            resource_meta={
                                "resource_name": f"Data.gov.hk: {dataset_id}",
                                "resource_url": api_url,
                                "format": "api",
                                "metadata": {"resources": resources},
                            },
                        )
        except httpx.HTTPError as exc:
            logger.warning("data.gov.hk API call failed: %s", exc)

        # Fallback: just store as metadata
        return ConnectorResult(
            dataset_meta={
                "name": candidate_or_resource.get("title") or dataset_id,
                "source_url": api_url,
                "access_type": "api",
                "geography": "Hong Kong",
                "portal": "data.gov.hk",
                "metadata": {"data_gov_hk_id": dataset_id},
            },
            needs_connector=True,
        )

    def query(self, dataset_or_resource: dict[str, Any], params: dict | None = None) -> ConnectorResult:
        """Query data.gov.hk datastore API for actual data."""
        meta = dataset_or_resource.get("metadata", {})
        dataset_id = meta.get("data_gov_hk_id")
        if not dataset_id:
            return ConnectorResult(success=False, error="No data.gov.hk dataset ID")

        # Try datastore_search API
        api_url = f"https://data.gov.hk/en/api/3/action/datastore_search"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(api_url, params={"id": dataset_id, "limit": params.get("limit", 100)})
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        result = data.get("result", {})
                        records = result.get("records", [])
                        return ConnectorResult(
                            rows=records,
                            snapshot_meta={
                                "row_count": len(records),
                                "column_count": len(records[0]) if records else 0,
                                "status": "captured",
                                "query_params": params,
                                "metadata": {"source": "data.gov.hk_api"},
                            },
                        )
        except httpx.HTTPError as exc:
            return ConnectorResult(success=False, error=f"API query failed: {exc}")

        return ConnectorResult(success=False, error="No data returned")


class PatentIPSourceConnector(SourceConnector):
    """Handles HK patent/IP/statistics rows from 香港专利0508.xlsx."""

    def can_handle(self, candidate: dict[str, Any]) -> bool:
        source_set = candidate.get("source_set", "")
        return source_set == "hk_patent"

    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        meta = candidate.get("raw_row_metadata", {})
        return {
            "type": "patent_ip",
            "category": meta.get("类别", ""),
            "system": meta.get("名称 / 系统", ""),
        }

    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        meta = candidate.get("raw_row_metadata", {})
        kind = candidate.get("source_kind", "unknown")
        url = candidate.get("url", "")

        # If it's a direct download, route to file connector
        if kind in ("downloadable_csv", "downloadable_xlsx"):
            return GenericDownloadableFileConnector().discover(candidate)

        # Portal/search systems become metadata-only candidates
        return ConnectorResult(
            dataset_meta={
                "name": meta.get("名称 / 系统", candidate.get("title", "")),
                "source_url": url,
                "access_type": "portal" if kind in ("search_portal", "official_portal") else "unknown",
                "geography": "Hong Kong",
                "description": meta.get("用途 / 数据内容", ""),
                "portal": urlparse(url).netloc,
                "topic": "patents_ip",
            },
            needs_connector=kind in ("search_portal", "official_portal"),
        )

    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        kind = candidate_or_resource.get("source_kind", "")
        if kind in ("downloadable_csv", "downloadable_xlsx"):
            return GenericDownloadableFileConnector().sync(candidate_or_resource, limit=limit)
        # Portals can't be synced — store as metadata
        return ConnectorResult(success=True, needs_connector=True)


class UniversityTTOConnector(SourceConnector):
    """Handles TTO/incubator/startup-list rows from 香港tto0508.xlsx."""

    def can_handle(self, candidate: dict[str, Any]) -> bool:
        source_set = candidate.get("source_set", "")
        return source_set == "hk_tto"

    def inspect(self, candidate: dict[str, Any]) -> dict[str, Any]:
        meta = candidate.get("raw_row_metadata", {})
        return {
            "type": "university_tto",
            "school": meta.get("学校", ""),
            "row_type": meta.get("类型", ""),
        }

    def discover(self, candidate: dict[str, Any]) -> ConnectorResult:
        meta = candidate.get("raw_row_metadata", {})
        kind = candidate.get("source_kind", "unknown")
        url = candidate.get("url", "")
        school = meta.get("学校", "")
        row_type = meta.get("类型", "")
        name_desc = meta.get("名称 / 说明", "")

        # Determine ecosystem_category
        if row_type == "初创列表" or kind == "startup_directory":
            eco_cat = "startup_directory"
        elif row_type == "孵化器":
            eco_cat = "incubator"
        elif row_type == "TTO":
            eco_cat = "university_tto"
        else:
            eco_cat = "ecosystem_organization"

        return ConnectorResult(
            dataset_meta={
                "name": f"{school} - {name_desc}",
                "source_url": url,
                "access_type": "portal",
                "geography": "Hong Kong",
                "description": name_desc,
                "topic": eco_cat,
            },
        )

    def sync(self, candidate_or_resource: dict[str, Any], *, limit: int = 100) -> ConnectorResult:
        # TTO pages become org records, not data snapshots
        return ConnectorResult(success=True)


# --- Connector registry ---

CONNECTORS: list[type[SourceConnector]] = [
    DataGovHKConnector,
    PatentIPSourceConnector,
    UniversityTTOConnector,
    GenericDownloadableFileConnector,
    GenericHTMLTableConnector,
    GenericOrganizationPageConnector,
    GenericPDFReportCandidateConnector,
]


def get_connector_for_candidate(candidate: dict[str, Any]) -> SourceConnector | None:
    """Find the first connector that can handle this candidate."""
    for cls in CONNECTORS:
        connector = cls()
        if connector.can_handle(candidate):
            return connector
    return None


# --- Helpers ---

def _filename_from_url(url: str) -> str:
    """Extract a reasonable filename from a URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path:
        name = Path(path).stem or parsed.netloc
    else:
        name = parsed.netloc
    # Clean up
    return name.replace("-", " ").replace("_", " ").strip() or "Unknown"


def _extract_data_gov_hk_id(url: str) -> str | None:
    """Extract dataset ID from a data.gov.hk URL."""
    parsed = urlparse(url)
    path = parsed.path
    # Pattern: /en-data/dataset/<id> or /dataset/<id>
    import re
    match = re.search(r"/dataset/([a-zA-Z0-9_-]+)", path)
    if match:
        return match.group(1)
    return None
