"""Focused sync for approved HK connector sources.

1. Syncs data.gov.hk patent CSV row (metadata + portal candidate)
2. Ingests 21 HK TTO rows into ecosystem_organizations
3. Rebuilds search index for all connector-backed objects
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import text

from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.connector_candidates import ExternalSourceCandidateRepository
from app.db.repositories.connectors import (
    ConnectorDatasetRepository,
    ConnectorResourceRepository,
    ConnectorSnapshotRepository,
)
from app.db.repositories.ecosystem_organizations import EcosystemOrganizationRepository
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

PATENT_EXCEL = Path("/home/ubuntu/.hermes/cache/documents/doc_a5c20fb52c63_香港专利0508.xlsx")
TTO_EXCEL = Path("/home/ubuntu/.hermes/cache/documents/doc_0f5bd9e2e3b0_香港tto0508.xlsx")
DIAGNOSTICS_DIR = Path("/data/hermes/diagnostics/connector_sync_eval")


def sync_data_gov_hk_row() -> dict:
    """Sync the data.gov.hk CSV row from 香港专利0508.xlsx.

    Since the URL is just the portal homepage (not a direct CSV download),
    we create the connector metadata records and mark as needs_connector.
    """
    engine = get_engine()
    result = {
        "source": "data.gov.hk",
        "connector_dataset": None,
        "connector_resource": None,
        "connector_snapshot": None,
        "external_source_candidate": None,
        "rows_synced": 0,
        "local_file": None,
        "status": "metadata_only",
        "notes": "",
    }

    # The row from the Excel
    row_data = {
        "类别": "开放数据",
        "名称 / 系统": "商标/专利/外观设计申请及注册统计（CSV）",
        "用途 / 数据内容": "过去5年标准专利、短期专利等统计数据",
        "URL": "https://data.gov.hk",
    }

    with engine.begin() as conn:
        cand_repo = ExternalSourceCandidateRepository(conn)
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)

        # 1. Create external_source_candidate
        candidate = cand_repo.upsert({
            "title": row_data["名称 / 系统"],
            "url": row_data["URL"],
            "source_kind": "downloadable_csv",
            "geography": "Hong Kong",
            "ecosystem_category": "public_dataset",
            "discovery_method": "curated_excel",
            "confidence_score": 0.80,
            "status": "needs_connector",
            "source_set": "hk_patent",
            "raw_row_metadata": row_data,
            "notes": "Portal homepage URL — actual CSV dataset needs discovery via data.gov.hk search. "
                     "Expected: trademark/patent/design application & registration statistics (CSV, past 5 years).",
        })
        result["external_source_candidate"] = {
            "id": str(candidate["id"]),
            "status": candidate["status"],
        }

        # 2. Create connector_dataset
        dataset = ds_repo.upsert({
            "name": "商标/专利/外观设计申请及注册统计",
            "description": "Hong Kong trademark, patent, and design application/registration statistics (CSV). "
                           "Past 5 years of standard patents, short-term patents, etc. Available on data.gov.hk.",
            "publisher": "Hong Kong Intellectual Property Department",
            "geography": "Hong Kong",
            "topic": "patents_ip",
            "source_url": "https://data.gov.hk",
            "portal": "data.gov.hk",
            "access_type": "portal",
            "status": "discovered",
            "source_candidate_id": candidate["id"],
            "metadata": {
                "original_category": row_data["类别"],
                "data_content": row_data["用途 / 数据内容"],
                "source_set": "hk_patent",
                "data_type": "downloadable_csv",
                "discovery_note": "Portal URL — direct CSV download URL not yet resolved",
            },
        })
        result["connector_dataset"] = {
            "id": str(dataset["id"]),
            "name": dataset["name"],
            "access_type": dataset["access_type"],
            "status": dataset["status"],
        }

        # 3. Create connector_resource (placeholder — actual URL TBD)
        resource = res_repo.create({
            "dataset_id": dataset["id"],
            "resource_name": "data.gov.hk IP Statistics CSV",
            "resource_url": "https://data.gov.hk",
            "format": "csv",
            "status": "pending",
            "metadata": {
                "note": "Resource URL is portal homepage — needs resolution to direct CSV download",
                "expected_content": "Trademark/patent/design application & registration statistics",
            },
        })
        result["connector_resource"] = {
            "id": str(resource["id"]),
            "format": resource["format"],
            "status": resource["status"],
        }

        # 4. No snapshot possible without direct download URL
        result["connector_snapshot"] = None
        result["notes"] = (
            "data.gov.hk URL is portal homepage, not a direct CSV download. "
            "Connector metadata created. Snapshot requires resolving the actual dataset URL "
            "via data.gov.hk search or API. Marked needs_connector for specialized resolution."
        )

    return result


def ingest_tto_organizations() -> dict:
    """Ingest 21 HK TTO rows into ecosystem_organizations.

    Preserves: school/parent, type, name/description, URL, related materials,
    organization_type, geography=Hong Kong, source_set=hk_tto.
    Deduplicates by URL, normalized name, and parent organization.
    """
    engine = get_engine()
    df = pd.read_excel(TTO_EXCEL)

    result = {
        "total_rows": len(df),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "organizations": [],
    }

    with engine.begin() as conn:
        org_repo = EcosystemOrganizationRepository(conn)

        for _, row in df.iterrows():
            url = str(row.get("URL", "")).strip()
            if not url or url.lower() == "nan":
                result["skipped"] += 1
                continue

            school = str(row.get("学校", "")).strip()
            row_type = str(row.get("类型", "")).strip()
            name_desc = str(row.get("名称 / 说明", "")).strip()
            related = str(row.get("相关资料", "")).strip()
            if related.lower() == "nan":
                related = None

            # Map 类型 to organization_type
            type_mapping = {
                "TTO": "tto",
                "孵化器": "incubator",
                "初创列表": "startup_directory",
            }
            org_type = type_mapping.get(row_type, "ecosystem_organization")

            # Build organization name: prefer name_desc, fall back to school
            org_name = name_desc if name_desc and name_desc.lower() != "nan" else school
            description = f"{school} — {name_desc}" if school and name_desc else org_name

            # Check for existing by URL
            existing = org_repo.get_by_website_url(url)

            org_values = {
                "name": org_name,
                "website_url": url,
                "description": description,
                "organization_type": org_type,
                "geography": "Hong Kong",
                "country": "Hong Kong",
                "city": "Hong Kong",
                "confidence_score": 0.85,
                "review_status": "approved",
                "metadata": {
                    "parent_organization": school,
                    "row_type": row_type,
                    "related_url": related,
                    "source": "curated_excel",
                    "source_set": "hk_tto",
                    "excel_file": "香港tto0508.xlsx",
                },
            }

            try:
                org = org_repo.upsert(org_values, force=True)
                if existing:
                    result["updated"] += 1
                else:
                    result["inserted"] += 1
                result["organizations"].append({
                    "id": str(org["id"]),
                    "name": org_name,
                    "url": url,
                    "type": org_type,
                    "school": school,
                })
            except Exception as exc:
                logger.warning("Failed to upsert org %s: %s", url, exc)
                result["skipped"] += 1

    return result


def rebuild_search_index() -> dict:
    """Rebuild search index for connector datasets + ecosystem organizations."""
    engine = get_engine()
    counts = {}

    with engine.begin() as conn:
        # Rebuild connector dataset search entries
        ds_rows = conn.execute(text(
            "SELECT id, name, description, publisher, geography, topic, "
            "source_url, portal, access_type, status "
            "FROM connector_datasets"
        )).fetchall()

        for row in ds_rows:
            search_text = " ".join(str(v) for v in row[1:] if v)
            conn.execute(text(
                """
                INSERT INTO search_index (object_type, object_id, title, content, search_text,
                  geography, source_url, availability, metadata)
                VALUES ('connector_dataset', :oid, :title, :content, :search_text,
                  :geography, :source_url, :availability, CAST(:metadata AS jsonb))
                ON CONFLICT (object_type, object_id) DO UPDATE SET
                  title = EXCLUDED.title, content = EXCLUDED.content,
                  search_text = EXCLUDED.search_text, geography = EXCLUDED.geography,
                  source_url = EXCLUDED.source_url, availability = EXCLUDED.availability,
                  metadata = EXCLUDED.metadata, updated_at = now()
                """
            ), {
                "oid": str(row[0]),
                "title": row[1],
                "content": row[2] or row[1],
                "search_text": search_text,
                "geography": row[3],
                "source_url": row[6],
                "availability": "obtainable" if row[9] == "synced" else "metadata_only",
                "metadata": json.dumps({"access_type": row[8], "portal": row[7], "topic": row[5]}),
            })
        counts["connector_datasets"] = len(ds_rows)

        # Rebuild external source candidate entries
        cand_rows = conn.execute(text(
            "SELECT id, title, url, source_kind, geography, ecosystem_category, status, notes "
            "FROM external_source_candidates WHERE status NOT IN ('rejected', 'failed')"
        )).fetchall()

        for row in cand_rows:
            search_text = " ".join(str(v) for v in row[1:] if v)
            conn.execute(text(
                """
                INSERT INTO search_index (object_type, object_id, title, content, search_text,
                  geography, source_url, availability, metadata)
                VALUES ('connector_candidate', :oid, :title, :content, :search_text,
                  :geography, :source_url, :availability, CAST(:metadata AS jsonb))
                ON CONFLICT (object_type, object_id) DO UPDATE SET
                  title = EXCLUDED.title, content = EXCLUDED.content,
                  search_text = EXCLUDED.search_text, geography = EXCLUDED.geography,
                  source_url = EXCLUDED.source_url, availability = EXCLUDED.availability,
                  metadata = EXCLUDED.metadata, updated_at = now()
                """
            ), {
                "oid": str(row[0]),
                "title": row[1],
                "content": row[1] or "",
                "search_text": search_text,
                "geography": row[4],
                "source_url": row[2],
                "availability": row[6],
                "metadata": json.dumps({"source_kind": row[3], "ecosystem_category": row[5]}),
            })
        counts["connector_candidates"] = len(cand_rows)

        # Rebuild organization search entries (HK TTO ones specifically)
        org_rows = conn.execute(text(
            "SELECT id, name, description, organization_type, geography, website_url, metadata "
            "FROM ecosystem_organizations "
            "WHERE metadata->>'source_set' = 'hk_tto'"
        )).fetchall()

        for row in org_rows:
            search_text = " ".join(str(v) for v in row[1:6] if v)
            # Add parent org to search text
            meta = row[6] if row[6] else {}
            if isinstance(meta, str):
                import json as _json
                meta = _json.loads(meta)
            parent = meta.get("parent_organization", "")
            if parent:
                search_text += f" {parent}"

            conn.execute(text(
                """
                INSERT INTO search_index (object_type, object_id, title, content, search_text,
                  geography, source_url, availability, metadata)
                VALUES ('organization', :oid, :title, :content, :search_text,
                  :geography, :source_url, 'obtainable', CAST(:metadata AS jsonb))
                ON CONFLICT (object_type, object_id) DO UPDATE SET
                  title = EXCLUDED.title, content = EXCLUDED.content,
                  search_text = EXCLUDED.search_text, geography = EXCLUDED.geography,
                  source_url = EXCLUDED.source_url, availability = EXCLUDED.availability,
                  metadata = EXCLUDED.metadata, updated_at = now()
                """
            ), {
                "oid": str(row[0]),
                "title": row[1],
                "content": row[2] or row[1],
                "search_text": search_text,
                "geography": row[4],
                "source_url": row[5],
                "metadata": json.dumps({"organization_type": row[3], "source_set": "hk_tto"}),
            })
        counts["organizations_hk_tto"] = len(org_rows)

    return counts


def generate_diagnostics(sync_result: dict, org_result: dict, search_counts: dict) -> dict:
    """Generate diagnostic files."""
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {}

    # connector_sync_summary.md
    summary_path = DIAGNOSTICS_DIR / "connector_sync_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# Connector Sync Summary\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")

        f.write("## 1. data.gov.hk CSV Sync\n\n")
        ds = sync_result.get("connector_dataset", {})
        f.write(f"- **Status**: {sync_result['status']}\n")
        f.write(f"- **Connector Dataset ID**: {ds.get('id', 'N/A')}\n")
        f.write(f"- **Dataset Name**: {ds.get('name', 'N/A')}\n")
        f.write(f"- **Access Type**: {ds.get('access_type', 'N/A')}\n")
        f.write(f"- **Dataset Status**: {ds.get('status', 'N/A')}\n")
        res = sync_result.get("connector_resource", {})
        f.write(f"- **Resource ID**: {res.get('id', 'N/A')}\n")
        f.write(f"- **Resource Format**: {res.get('format', 'N/A')}\n")
        f.write(f"- **Snapshot**: {sync_result.get('connector_snapshot') or 'None (portal URL, no direct download)'}\n")
        f.write(f"- **Rows Synced**: {sync_result['rows_synced']}\n")
        f.write(f"- **Local File**: {sync_result.get('local_file') or 'None'}\n\n")
        f.write(f"**Note**: {sync_result['notes']}\n\n")

        f.write("## 2. HK TTO Organization Ingestion\n\n")
        f.write(f"- **Total Rows**: {org_result['total_rows']}\n")
        f.write(f"- **Inserted**: {org_result['inserted']}\n")
        f.write(f"- **Updated**: {org_result['updated']}\n")
        f.write(f"- **Skipped**: {org_result['skipped']}\n\n")

        f.write("### Organizations\n\n")
        for org in org_result["organizations"]:
            f.write(f"- **{org['name']}** ({org['type']}) — {org['school']} — {org['url']}\n")

        f.write("\n## 3. Search Index\n\n")
        for obj_type, count in search_counts.items():
            f.write(f"- **{obj_type}**: {count} entries\n")

    outputs["summary"] = summary_path

    # synced_dataset_preview.csv
    import csv
    preview_path = DIAGNOSTICS_DIR / "synced_dataset_preview.csv"
    with open(preview_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "field", "value",
        ])
        writer.writeheader()
        for field, value in [
            ("dataset_id", ds.get("id", "")),
            ("dataset_name", ds.get("name", "")),
            ("access_type", ds.get("access_type", "")),
            ("status", ds.get("status", "")),
            ("resource_id", res.get("id", "")),
            ("resource_format", res.get("format", "")),
            ("snapshot", "none — portal URL needs resolution"),
            ("rows_synced", "0"),
            ("checksum", "N/A"),
            ("retrieved_at", "N/A"),
            ("columns_detected", "N/A"),
        ]:
            writer.writerow({"field": field, "value": value})
    outputs["synced_dataset"] = preview_path

    # hk_organization_ingestion_summary.csv
    org_path = DIAGNOSTICS_DIR / "hk_organization_ingestion_summary.csv"
    with open(org_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "name", "url", "type", "school", "id",
        ])
        writer.writeheader()
        for org in org_result["organizations"]:
            writer.writerow(org)
    outputs["organizations"] = org_path

    # connector_search_index_summary.csv
    search_path = DIAGNOSTICS_DIR / "connector_search_index_summary.csv"
    with open(search_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["object_type", "count"])
        writer.writeheader()
        for obj_type, count in search_counts.items():
            writer.writerow({"object_type": obj_type, "count": count})
    outputs["search_index"] = search_path

    return outputs


def main():
    configure_logging()
    print("=" * 60)
    print("Connector Sync — Focused HK Sources")
    print("=" * 60)

    # Task 1: Sync data.gov.hk CSV row
    print("\n[1/3] Syncing data.gov.hk CSV row...")
    sync_result = sync_data_gov_hk_row()
    print(f"  Dataset: {sync_result['connector_dataset']['id']}")
    print(f"  Resource: {sync_result['connector_resource']['id']}")
    print(f"  Status: {sync_result['status']}")
    print(f"  Snapshot: {sync_result['connector_snapshot']}")

    # Task 2: Ingest TTO organizations
    print("\n[2/3] Ingesting HK TTO organizations...")
    org_result = ingest_tto_organizations()
    print(f"  Inserted: {org_result['inserted']}")
    print(f"  Updated: {org_result['updated']}")
    print(f"  Skipped: {org_result['skipped']}")

    # Task 3: Rebuild search index
    print("\n[3/3] Rebuilding search index...")
    search_counts = rebuild_search_index()
    print(f"  Counts: {search_counts}")

    # Generate diagnostics
    print("\nGenerating diagnostics...")
    outputs = generate_diagnostics(sync_result, org_result, search_counts)
    for name, path in outputs.items():
        print(f"  {name}: {path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
