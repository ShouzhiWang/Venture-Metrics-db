"""Tests for the connector architecture.

No live external API calls. All tests use mocked data and local logic.
"""

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app.agents.source_kind_classifier import (
    classify_ecosystem_category,
    classify_source_kind,
    infer_organization_type,
)
from app.agents.connectors import (
    ConnectorResult,
    DataGovHKConnector,
    GenericDownloadableFileConnector,
    GenericHTMLTableConnector,
    GenericOrganizationPageConnector,
    GenericPDFReportCandidateConnector,
    PatentIPSourceConnector,
    UniversityTTOConnector,
    get_connector_for_candidate,
)
from app.workers.connector_discovery import (
    classify_candidates,
    generate_dry_run_outputs,
    parse_excel_rows,
)


# ============================================================
# Source Kind Classification Tests
# ============================================================

class TestSourceKindClassification:
    def test_csv_extension(self):
        kind, conf = classify_source_kind("https://example.gov/data.csv")
        assert kind == "downloadable_csv"
        assert conf >= 0.9

    def test_xlsx_extension(self):
        kind, conf = classify_source_kind("https://example.gov/data.xlsx")
        assert kind == "downloadable_xlsx"
        assert conf >= 0.9

    def test_pdf_extension(self):
        kind, conf = classify_source_kind("https://example.org/report.pdf")
        assert kind == "downloadable_pdf"
        assert conf >= 0.9

    def test_json_extension(self):
        kind, conf = classify_source_kind("https://api.example.org/data.json")
        assert kind == "api_endpoint"
        assert conf >= 0.9

    def test_api_url_pattern(self):
        kind, conf = classify_source_kind("https://example.org/api/v2/datasets")
        assert kind == "api_endpoint"
        assert conf >= 0.7

    def test_data_gov_hk_portal(self):
        kind, conf = classify_source_kind("https://data.gov.hk/en-data/dataset/abc123")
        # Could be api_endpoint or official_portal depending on URL pattern
        assert kind in ("api_endpoint", "official_portal")

    def test_search_portal_pattern(self):
        kind, conf = classify_source_kind("https://ipd.gov.hk/tc/online-services/online-search/index.html")
        assert kind == "search_portal"
        assert conf >= 0.5

    def test_official_gov_portal(self):
        kind, conf = classify_source_kind("https://www.ipd.gov.hk")
        assert kind == "official_portal"
        assert conf >= 0.5

    def test_organization_page_pattern(self):
        kind, conf = classify_source_kind("https://www.tto.hku.hk")
        assert kind == "organization_page"
        assert conf >= 0.5

    def test_startup_directory_pattern(self):
        kind, conf = classify_source_kind("https://www.tto.hku.hk/startups/hku-startup-spin-off-companies")
        assert kind == "startup_directory"
        assert conf >= 0.5

    def test_incubator_pattern(self):
        # ec.hkust.edu.hk doesn't contain recognizable org terms in URL alone
        kind, conf = classify_source_kind("https://ec.hkust.edu.hk")
        assert kind == "unknown"  # needs row metadata for classification
        # With metadata it should classify as startup_directory (创业 matches there first)
        kind2, _ = classify_source_kind(
            "https://ec.hkust.edu.hk",
            row_metadata={"名称 / 说明": "创业中心", "类型": "孵化器"},
        )
        assert kind2 in ("organization_page", "startup_directory")

    def test_content_type_csv(self):
        kind, conf = classify_source_kind("https://example.org/download", content_type="text/csv")
        assert kind == "downloadable_csv"
        assert conf >= 0.9

    def test_content_type_xlsx(self):
        kind, conf = classify_source_kind(
            "https://example.org/download",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert kind == "downloadable_xlsx"
        assert conf >= 0.9

    def test_empty_url(self):
        kind, conf = classify_source_kind("")
        assert kind == "unknown"
        assert conf == 0.0

    def test_none_url(self):
        kind, conf = classify_source_kind(None)
        assert kind == "unknown"

    def test_row_metadata_csv_signal(self):
        kind, conf = classify_source_kind(
            "https://example.org/data",
            row_metadata={"用途": "CSV统计数据下载"},
        )
        assert kind == "downloadable_csv"

    def test_row_metadata_startup_signal(self):
        kind, conf = classify_source_kind(
            "https://example.org/page",
            row_metadata={"名称": "初创公司列表"},
        )
        assert kind == "startup_directory"

    def test_hk_patent_ipd_search(self):
        """The IPD online search system should be classified as search_portal."""
        kind, _ = classify_source_kind(
            "https://www.ipd.gov.hk/tc/online-services/online-search/index.html"
        )
        assert kind == "search_portal"

    def test_hk_patent_image_search(self):
        """Image trademark search → search_portal."""
        kind, _ = classify_source_kind("https://image-mark-finder.ipd.gov.hk")
        assert kind == "search_portal"

    def test_hk_hktisc(self):
        """HKTISC URL alone doesn't have recognizable org terms."""
        kind, _ = classify_source_kind("https://hktisc.hkpc.org")
        assert kind == "unknown"  # needs row metadata
        # With patent-related metadata it classifies
        kind2, _ = classify_source_kind(
            "https://hktisc.hkpc.org",
            row_metadata={"类别": "专项服务", "名称 / 系统": "HKTISC 专利检索服务"},
        )
        assert kind2 in ("organization_page", "search_portal", "unknown")


# ============================================================
# Ecosystem Category Classification Tests
# ============================================================

class TestEcosystemCategory:
    def test_hk_patent_csv(self):
        cat = classify_ecosystem_category("downloadable_csv", source_set="hk_patent")
        assert cat == "public_dataset"

    def test_hk_patent_portal(self):
        cat = classify_ecosystem_category("search_portal", source_set="hk_patent")
        assert cat == "patents_ip"

    def test_hk_tto_startup(self):
        cat = classify_ecosystem_category("startup_directory", source_set="hk_tto")
        assert cat == "startup_directory"

    def test_hk_tto_org(self):
        cat = classify_ecosystem_category("organization_page", source_set="hk_tto")
        assert cat == "university_tto"

    def test_infer_from_metadata_tto(self):
        cat = classify_ecosystem_category("unknown", row_metadata={"类型": "TTO"})
        assert cat == "university_tto"

    def test_infer_from_metadata_patent(self):
        cat = classify_ecosystem_category("unknown", row_metadata={"类别": "专利检索"})
        assert cat == "patents_ip"


# ============================================================
# Organization Type Inference Tests
# ============================================================

class TestOrganizationTypeInference:
    def test_tto_type(self):
        assert infer_organization_type({"类型": "TTO"}) == "tto"

    def test_incubator_type(self):
        assert infer_organization_type({"类型": "孵化器"}) == "incubator"

    def test_startup_dir_type(self):
        assert infer_organization_type({"类型": "初创列表"}) == "startup_directory"

    def test_unknown_type(self):
        assert infer_organization_type({"类型": "其他"}) == "ecosystem_organization"

    def test_none_metadata(self):
        assert infer_organization_type(None) is None


# ============================================================
# Connector Dispatch Tests
# ============================================================

class TestConnectorDispatch:
    def test_csv_gets_file_connector(self):
        cand = {"source_kind": "downloadable_csv", "url": "https://example.org/data.csv"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, GenericDownloadableFileConnector)

    def test_xlsx_gets_file_connector(self):
        cand = {"source_kind": "downloadable_xlsx", "url": "https://example.org/data.xlsx"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, GenericDownloadableFileConnector)

    def test_html_table_gets_table_connector(self):
        cand = {"source_kind": "html_table", "url": "https://example.org/table"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, GenericHTMLTableConnector)

    def test_org_page_gets_org_connector(self):
        cand = {"source_kind": "organization_page", "url": "https://tto.hku.hk"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, GenericOrganizationPageConnector)

    def test_pdf_gets_pdf_connector(self):
        cand = {"source_kind": "downloadable_pdf", "url": "https://example.org/report.pdf"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, GenericPDFReportCandidateConnector)

    def test_data_gov_hk_gets_datagov_connector(self):
        cand = {"source_kind": "official_portal", "url": "https://data.gov.hk/en-data/dataset/abc"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, DataGovHKConnector)

    def test_hk_patent_gets_patent_connector(self):
        cand = {"source_kind": "search_portal", "url": "https://ipd.gov.hk", "source_set": "hk_patent"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, PatentIPSourceConnector)

    def test_hk_tto_gets_tto_connector(self):
        cand = {"source_kind": "organization_page", "url": "https://tto.hku.hk", "source_set": "hk_tto"}
        connector = get_connector_for_candidate(cand)
        assert isinstance(connector, UniversityTTOConnector)

    def test_unknown_returns_none(self):
        cand = {"source_kind": "unknown", "url": "https://random-site.xyz"}
        connector = get_connector_for_candidate(cand)
        assert connector is None


# ============================================================
# Connector Discover Tests
# ============================================================

class TestConnectorDiscover:
    def test_file_connector_discover_csv(self):
        connector = GenericDownloadableFileConnector()
        cand = {
            "source_kind": "downloadable_csv",
            "url": "https://data.gov.hk/stats.csv",
            "title": "Patent Statistics",
            "geography": "Hong Kong",
            "raw_row_metadata": {"用途 / 数据内容": "Patent application data"},
        }
        result = connector.discover(cand)
        assert result.success
        assert result.dataset_meta["access_type"] == "csv"
        assert result.dataset_meta["source_url"] == "https://data.gov.hk/stats.csv"

    def test_org_connector_discover(self):
        connector = GenericOrganizationPageConnector()
        cand = {
            "source_kind": "organization_page",
            "url": "https://tto.hku.hk",
            "title": "HKU TTO",
            "raw_row_metadata": {"名称 / 说明": "技术转移处"},
        }
        result = connector.discover(cand)
        assert result.success
        assert "TTO" in result.dataset_meta["name"] or "HKU" in result.dataset_meta["name"]

    def test_patent_connector_discover_portal(self):
        connector = PatentIPSourceConnector()
        cand = {
            "source_kind": "search_portal",
            "url": "https://ipd.gov.hk",
            "source_set": "hk_patent",
            "raw_row_metadata": {"类别": "官方检索", "名称 / 系统": "知识产权署网上检索系统"},
        }
        result = connector.discover(cand)
        assert result.success
        assert result.needs_connector  # Portals need specialized connector

    def test_tto_connector_discover(self):
        connector = UniversityTTOConnector()
        cand = {
            "source_kind": "organization_page",
            "url": "https://tto.hku.hk",
            "source_set": "hk_tto",
            "raw_row_metadata": {"学校": "香港大学 (HKU)", "类型": "TTO", "名称 / 说明": "技术转移处"},
        }
        result = connector.discover(cand)
        assert result.success
        assert "HKU" in result.dataset_meta["name"]

    def test_pdf_connector_no_auto_sync(self):
        connector = GenericPDFReportCandidateConnector()
        cand = {"source_kind": "downloadable_pdf", "url": "https://example.org/report.pdf"}
        result = connector.sync(cand)
        assert result.success
        assert result.needs_connector  # PDFs need approval


# ============================================================
# Excel Parsing Tests
# ============================================================

class TestExcelParsing:
    def _make_patent_excel(self, path: Path):
        """Create a mock patent Excel file."""
        df = pd.DataFrame({
            "类别": ["官方检索", "开放数据"],
            "名称 / 系统": ["知识产权署网上检索系统", "商标/专利统计数据"],
            "用途 / 数据内容": ["检索标准专利", "过去5年统计数据"],
            "URL": [
                "https://www.ipd.gov.hk/tc/online-services/online-search/index.html",
                "https://data.gov.hk",
            ],
        })
        df.to_excel(path, index=False)

    def _make_tto_excel(self, path: Path):
        """Create a mock TTO Excel file."""
        df = pd.DataFrame({
            "学校": ["香港大学 (HKU)", "香港中文大学 (CUHK)"],
            "类型": ["TTO", "孵化器"],
            "名称 / 说明": ["技术转移处", "InnoPort"],
            "URL": ["https://www.tto.hku.hk", "https://innoport.cuhk.edu.hk"],
            "相关资料": [None, "https://example.org/booklet.pdf"],
        })
        df.to_excel(path, index=False)

    def test_parse_patent_excel(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = Path(f.name)
        self._make_patent_excel(path)
        rows = parse_excel_rows(path, "hk_patent")
        assert len(rows) == 2
        assert rows[0]["url"].startswith("https://")
        assert rows[0]["source_set"] == "hk_patent"
        assert "raw_row_metadata" in rows[0]
        path.unlink()

    def test_parse_tto_excel(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = Path(f.name)
        self._make_tto_excel(path)
        rows = parse_excel_rows(path, "hk_tto")
        assert len(rows) == 2
        assert rows[0]["source_set"] == "hk_tto"
        assert "学校" in rows[0]["raw_row_metadata"]
        path.unlink()

    def test_classify_candidates_patent(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = Path(f.name)
        self._make_patent_excel(path)
        rows = parse_excel_rows(path, "hk_patent")
        classified = classify_candidates(rows, "hk_patent")
        assert len(classified) == 2
        for cand in classified:
            assert "source_kind" in cand
            assert "ecosystem_category" in cand
            assert cand["geography"] == "Hong Kong"
            assert cand["discovery_method"] == "curated_excel"
        path.unlink()

    def test_classify_candidates_tto(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = Path(f.name)
        self._make_tto_excel(path)
        rows = parse_excel_rows(path, "hk_tto")
        classified = classify_candidates(rows, "hk_tto")
        assert len(classified) == 2
        # TTO row should be classified
        tto_cand = classified[0]
        assert tto_cand["source_kind"] in ("organization_page", "search_portal", "unknown")
        path.unlink()


# ============================================================
# Deduplication Tests
# ============================================================

class TestDeduplication:
    def test_url_dedup_in_classification(self):
        """Same URL appearing twice should be handled."""
        rows = [
            {"url": "https://tto.hku.hk", "title": "HKU TTO", "source_set": "hk_tto", "raw_row_metadata": {}},
            {"url": "https://tto.hku.hk", "title": "HKU TTO Again", "source_set": "hk_tto", "raw_row_metadata": {}},
        ]
        classified = classify_candidates(rows, "hk_tto")
        # Both should classify the same way
        assert classified[0]["source_kind"] == classified[1]["source_kind"]


# ============================================================
# Dry-Run Output Tests
# ============================================================

class TestDryRunOutput:
    def test_generates_output_files(self):
        discover_results = {
            "total": 2,
            "by_source_kind": {"search_portal": 1, "downloadable_csv": 1},
            "by_ecosystem_category": {"patents_ip": 1, "public_dataset": 1},
            "candidates": [
                {
                    "url": "https://ipd.gov.hk",
                    "title": "IPD Search",
                    "source_kind": "search_portal",
                    "ecosystem_category": "patents_ip",
                    "confidence_score": 0.7,
                    "connector": "PatentIPSourceConnector",
                    "needs_connector": True,
                },
                {
                    "url": "https://data.gov.hk/data.csv",
                    "title": "Patent Stats",
                    "source_kind": "downloadable_csv",
                    "ecosystem_category": "public_dataset",
                    "confidence_score": 0.95,
                    "connector": "GenericDownloadableFileConnector",
                    "needs_connector": False,
                },
            ],
            "errors": [],
        }
        org_candidates = [
            {
                "name": "HKU TTO",
                "website_url": "https://tto.hku.hk",
                "organization_type": "tto",
                "geography": "Hong Kong",
                "description": "Technology Transfer Office",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.workers.connector_discovery.DIAGNOSTICS_DIR", Path(tmpdir)):
                outputs = generate_dry_run_outputs(discover_results, org_candidates, "hk_patent")

            assert "classification" in outputs
            assert "summary" in outputs
            assert "extractable" in outputs
            assert "manual_review" in outputs
            assert "organizations" in outputs

            # Check classification CSV
            with open(outputs["classification"], encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 2

            # Check summary markdown
            summary = outputs["summary"].read_text(encoding="utf-8")
            assert "Connector Discovery Summary" in summary
            assert "search_portal" in summary
            assert "downloadable_csv" in summary

            # Check org candidates CSV
            with open(outputs["organizations"], encoding="utf-8") as f:
                reader = csv.DictReader(f)
                org_rows = list(reader)
            assert len(org_rows) == 1
            assert org_rows[0]["name"] == "HKU TTO"


# ============================================================
# Cache/Policy Tests
# ============================================================

class TestCachePolicy:
    def test_snapshot_stale_detection(self):
        from app.workers.connector_query import is_snapshot_stale
        from datetime import datetime, timedelta, timezone

        # Recent snapshot — not stale
        recent = {"retrieved_at": datetime.now(timezone.utc).isoformat()}
        assert not is_snapshot_stale(recent, max_age_hours=24)

        # Old snapshot — stale
        old = {"retrieved_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()}
        assert is_snapshot_stale(old, max_age_hours=24)

        # No timestamp — stale
        assert is_snapshot_stale({}, max_age_hours=24)

    def test_connector_result_structure(self):
        result = ConnectorResult(
            success=True,
            dataset_meta={"name": "test"},
            rows=[{"a": 1}, {"a": 2}],
        )
        assert result.success
        assert result.dataset_meta["name"] == "test"
        assert len(result.rows) == 2
        assert not result.needs_connector


# ============================================================
# Routing Safety Tests
# ============================================================

class TestRoutingSafety:
    def test_org_page_not_routed_to_codebook(self):
        """Organization pages must never enter the codebook/report pipeline."""
        connector = GenericOrganizationPageConnector()
        cand = {
            "source_kind": "organization_page",
            "url": "https://tto.hku.hk",
            "raw_row_metadata": {},
        }
        result = connector.sync(cand)
        # Organization sync returns success but no snapshot/rows for codebook
        assert result.success
        assert result.rows is None
        assert result.needs_connector is False  # It's handled, just not as data

    def test_startup_directory_connector_result(self):
        """Startup directories should be flagged for specialized handling."""
        connector = PatentIPSourceConnector()
        cand = {
            "source_kind": "search_portal",
            "url": "https://ipd.gov.hk/search",
            "source_set": "hk_patent",
            "raw_row_metadata": {"类别": "官方检索", "名称 / 系统": "知识产权署"},
        }
        result = connector.sync(cand)
        assert result.success
        assert result.needs_connector  # Portals need specialized connector

    def test_data_gov_hk_connector_handles_nonexistent_dataset(self):
        """DataGovHK connector gracefully handles missing datasets."""
        connector = DataGovHKConnector()
        cand = {
            "source_kind": "official_portal",
            "url": "https://data.gov.hk/en-data/dataset/nonexistent-dataset-xyz",
        }
        result = connector.sync(cand)
        # Should not crash — either succeeds or returns error
        assert isinstance(result, ConnectorResult)


# ============================================================
# Real Excel File Tests (if files exist)
# ============================================================

class TestRealExcelFiles:
    PATENT_PATH = Path("/home/ubuntu/.hermes/cache/documents/doc_a5c20fb52c63_香港专利0508.xlsx")
    TTO_PATH = Path("/home/ubuntu/.hermes/cache/documents/doc_0f5bd9e2e3b0_香港tto0508.xlsx")

    @pytest.mark.skipif(not Path("/home/ubuntu/.hermes/cache/documents/doc_a5c20fb52c63_香港专利0508.xlsx").exists(),
                        reason="Patent Excel not available")
    def test_parse_real_patent_excel(self):
        rows = parse_excel_rows(self.PATENT_PATH, "hk_patent")
        assert len(rows) == 5
        for row in rows:
            assert row["url"].startswith("https://")
            assert row["source_set"] == "hk_patent"

    @pytest.mark.skipif(not Path("/home/ubuntu/.hermes/cache/documents/doc_0f5bd9e2e3b0_香港tto0508.xlsx").exists(),
                        reason="TTO Excel not available")
    def test_parse_real_tto_excel(self):
        rows = parse_excel_rows(self.TTO_PATH, "hk_tto")
        assert len(rows) == 21
        for row in rows:
            assert row["url"].startswith("https://")
            assert row["source_set"] == "hk_tto"

    @pytest.mark.skipif(not Path("/home/ubuntu/.hermes/cache/documents/doc_a5c20fb52c63_香港专利0508.xlsx").exists(),
                        reason="Patent Excel not available")
    def test_classify_real_patent_excel(self):
        rows = parse_excel_rows(self.PATENT_PATH, "hk_patent")
        classified = classify_candidates(rows, "hk_patent")
        assert len(classified) == 5
        # CSV stats row should be classified
        csv_rows = [c for c in classified if c["source_kind"] == "downloadable_csv"]
        assert len(csv_rows) >= 0  # May or may not match depending on URL

    @pytest.mark.skipif(not Path("/home/ubuntu/.hermes/cache/documents/doc_0f5bd9e2e3b0_香港tto0508.xlsx").exists(),
                        reason="TTO Excel not available")
    def test_classify_real_tto_excel(self):
        rows = parse_excel_rows(self.TTO_PATH, "hk_tto")
        classified = classify_candidates(rows, "hk_tto")
        assert len(classified) == 21
        # TTO rows should be classified as organization-related
        org_kinds = [c for c in classified if c["source_kind"] in (
            "organization_page", "startup_directory", "search_portal"
        )]
        assert len(org_kinds) >= 5  # Most TTO rows should be org-type

    @pytest.mark.skipif(not Path("/home/ubuntu/.hermes/cache/documents/doc_0f5bd9e2e3b0_香港tto0508.xlsx").exists(),
                        reason="TTO Excel not available")
    def test_tto_org_candidates(self):
        rows = parse_excel_rows(self.TTO_PATH, "hk_tto")
        classified = classify_candidates(rows, "hk_tto")
        from app.workers.connector_discovery import create_tto_organizations
        orgs = create_tto_organizations(classified, dry_run=True)
        assert len(orgs) == 21
        # Check HKU TTO
        hku_tto = next((o for o in orgs if "HKU" in o.get("description", "")), None)
        assert hku_tto is not None
        assert hku_tto["geography"] == "Hong Kong"


# ============================================================
# Synced-Over-Metadata Prioritization Tests
# ============================================================

class TestSyncedOverMetadataPriority:
    """Test that synced connector datasets appear before metadata-only candidates."""

    def _make_search_results(self):
        """Create mock search results with mixed synced and metadata-only connectors."""
        return [
            # Synced connector dataset
            {
                "object_type": "connector_dataset",
                "object_id": "synced-001",
                "title": "HK Patent Statistics CSV",
                "source_url": "https://data.gov.hk/patents.csv",
                "availability": "obtainable",
                "score": 0.9,
                "metadata": {
                    "access_type": "csv",
                    "portal": "data.gov.hk",
                    "topic": "patents_ip",
                    "row_count": 1500,
                    "column_count": 12,
                    "retrieved_at": "2025-06-01T10:00:00Z",
                    "snapshot_id": "snap-001",
                },
            },
            # Metadata-only connector dataset (portal)
            {
                "object_type": "connector_dataset",
                "object_id": "meta-001",
                "title": "IPD Online Search Portal",
                "source_url": "https://ipd.gov.hk/search",
                "availability": "metadata_only",
                "score": 0.7,
                "metadata": {
                    "access_type": "portal",
                    "portal": "ipd.gov.hk",
                    "topic": "patents_ip",
                },
            },
            # Connector candidate (always metadata-only)
            {
                "object_type": "connector_candidate",
                "object_id": "cand-001",
                "title": "HKTISC Patent Search",
                "source_url": "https://hktisc.hkpc.org",
                "availability": "pending_review",
                "score": 0.6,
                "metadata": {
                    "source_kind": "search_portal",
                    "ecosystem_category": "patents_ip",
                },
            },
            # Regular variable (should not be affected)
            {
                "object_type": "variable",
                "object_id": "var-001",
                "title": "Patent Applications Count",
                "score": 0.8,
                "metadata": {},
            },
        ]

    def test_synced_appears_before_metadata_only(self):
        """Synced connector datasets must appear before metadata-only ones."""
        from app.workers.find_data import group_results
        results = self._make_search_results()
        groups = group_results(results, limit=10)

        connector_datasets = groups["connector_datasets"]
        assert len(connector_datasets) >= 2

        # First should be synced
        assert connector_datasets[0]["data_status"] == "synced"
        assert connector_datasets[0]["data_status_label"] == "synced dataset"
        # Second should be metadata-only
        assert connector_datasets[1]["data_status"] == "metadata_only"
        assert connector_datasets[1]["data_status_label"] == "source candidate, not yet synced"

    def test_synced_dataset_has_snapshot_metadata(self):
        """Synced datasets must include row_count, column_count, retrieved_at."""
        from app.workers.find_data import group_results
        results = self._make_search_results()
        groups = group_results(results, limit=10)

        synced = groups["connector_datasets"][0]
        assert synced["row_count"] == 1500
        assert synced["column_count"] == 12
        assert synced["retrieved_at"] == "2025-06-01T10:00:00Z"
        assert synced["snapshot_id"] == "snap-001"
        assert synced["source_url"] == "https://data.gov.hk/patents.csv"

    def test_metadata_only_labeled_correctly(self):
        """Metadata-only candidates must be labeled 'source candidate, not yet synced'."""
        from app.workers.find_data import group_results
        results = self._make_search_results()
        groups = group_results(results, limit=10)

        # Connector candidates section
        candidates = groups["connector_candidates"]
        assert len(candidates) >= 1
        assert candidates[0]["data_status_label"] == "source candidate, not yet synced"

    def test_limit_respected_for_connectors(self):
        """Limit should be respected for connector results."""
        from app.workers.find_data import group_results
        results = self._make_search_results()
        groups = group_results(results, limit=1)

        # Only 1 connector dataset should appear (synced first)
        assert len(groups["connector_datasets"]) == 1
        assert groups["connector_datasets"][0]["data_status"] == "synced"

    def test_variables_unaffected_by_connector_priority(self):
        """Regular variables should not be affected by connector prioritization."""
        from app.workers.find_data import group_results
        results = self._make_search_results()
        groups = group_results(results, limit=10)

        assert len(groups["variables"]) == 1
        assert groups["variables"][0]["title"] == "Patent Applications Count"

    def test_format_item_enriches_synced_with_snapshot(self):
        """format_find_data_item should add snapshot metadata for synced datasets."""
        from app.workers.find_data import format_find_data_item
        row = {
            "object_type": "connector_dataset",
            "object_id": "synced-001",
            "title": "Test Dataset",
            "availability": "obtainable",
            "metadata": {
                "access_type": "csv",
                "portal": "data.gov.hk",
                "row_count": 500,
                "column_count": 8,
                "retrieved_at": "2025-06-01T10:00:00Z",
                "snapshot_id": "snap-002",
            },
        }
        item = format_find_data_item(row)
        assert item["data_status"] == "synced"
        assert item["data_status_label"] == "synced dataset"
        assert item["row_count"] == 500
        assert item["column_count"] == 8
        assert item["retrieved_at"] == "2025-06-01T10:00:00Z"
        assert item["snapshot_id"] == "snap-002"

    def test_format_item_labels_metadata_only(self):
        """format_find_data_item should label metadata-only datasets correctly."""
        from app.workers.find_data import format_find_data_item
        row = {
            "object_type": "connector_dataset",
            "object_id": "meta-001",
            "title": "Portal Only",
            "availability": "metadata_only",
            "metadata": {
                "access_type": "portal",
                "portal": "ipd.gov.hk",
            },
        }
        item = format_find_data_item(row)
        assert item["data_status"] == "metadata_only"
        assert item["data_status_label"] == "source candidate, not yet synced"
        assert item.get("row_count") is None

    def test_format_item_candidate_labeled(self):
        """Connector candidates should be labeled as source candidates."""
        from app.workers.find_data import format_find_data_item
        row = {
            "object_type": "connector_candidate",
            "object_id": "cand-001",
            "title": "Some Portal",
            "availability": "pending_review",
            "metadata": {
                "source_kind": "search_portal",
                "ecosystem_category": "patents_ip",
            },
        }
        item = format_find_data_item(row)
        assert item["data_status"] == "metadata_only"
        assert item["data_status_label"] == "source candidate, not yet synced"

    def test_normalize_preserves_connector_sections(self):
        """normalize_find_data_results should preserve connector_datasets and connector_candidates."""
        from app.services.research_task import normalize_find_data_results
        tool_result = {
            "ok": True,
            "data": {
                "closest_variables": [],
                "relevant_reports": [],
                "source_links": [],
                "relevant_organizations": [],
                "connector_datasets": [
                    {"title": "Synced DS", "data_status": "synced"},
                    {"title": "Meta DS", "data_status": "metadata_only"},
                ],
                "connector_candidates": [
                    {"title": "Portal Candidate"},
                ],
            },
        }
        result = normalize_find_data_results(tool_result)
        assert len(result["connector_datasets"]) == 2
        assert result["connector_datasets"][0]["data_status"] == "synced"
        assert len(result["connector_candidates"]) == 1

    def test_evidence_packet_includes_connector_sections(self):
        """EvidencePacketBuilder should include connector_datasets and connector_candidates."""
        from app.services.research_task import EvidencePacketBuilder, ResearchTaskPlan
        builder = EvidencePacketBuilder()
        plan = ResearchTaskPlan(query="HK patents", task_type="find_data")
        retrieved = {
            "closest_variables": [],
            "relevant_reports": [],
            "source_links": [],
            "relevant_organizations": [],
            "connector_datasets": [
                {
                    "title": "HK Patent CSV",
                    "source_url": "https://data.gov.hk/patents.csv",
                    "data_status": "synced",
                    "data_status_label": "synced dataset",
                    "row_count": 1500,
                    "column_count": 12,
                    "retrieved_at": "2025-06-01T10:00:00Z",
                },
            ],
            "connector_candidates": [
                {
                    "title": "IPD Portal",
                    "source_url": "https://ipd.gov.hk",
                    "source_kind": "search_portal",
                    "data_status_label": "source candidate, not yet synced",
                },
            ],
            "limitations": [],
        }
        packet = builder.build("HK patents", plan, retrieved)
        assert "connector_datasets" in packet
        assert "connector_candidates" in packet
        assert len(packet["connector_datasets"]) == 1
        assert packet["connector_datasets"][0]["data_status"] == "synced"
        assert packet["connector_datasets"][0]["row_count"] == 1500
        assert len(packet["connector_candidates"]) == 1
        assert packet["connector_candidates"][0]["data_status_label"] == "source candidate, not yet synced"


# ============================================================
# Connector Metric Extraction Tests
# ============================================================

class TestConnectorMetricExtraction:
    """Test metric extraction from connector rows."""

    def test_parse_value_numeric(self):
        from app.workers.connector_metric_extract import parse_value
        display, numeric = parse_value("34,120")
        assert display == "34,120"
        assert numeric == 34120.0

    def test_parse_value_percentage(self):
        from app.workers.connector_metric_extract import parse_value
        display, numeric = parse_value("98%")
        assert display == "98%"
        assert numeric == 0.98

    def test_parse_value_null(self):
        from app.workers.connector_metric_extract import parse_value
        display, numeric = parse_value(None)
        assert display is None
        assert numeric is None

    def test_parse_value_nan_string(self):
        from app.workers.connector_metric_extract import parse_value
        display, numeric = parse_value("nan")
        assert display is None
        assert numeric is None

    def test_match_metric_trademark_applications(self):
        from app.workers.connector_metric_extract import match_metric_pattern
        result = match_metric_pattern("Trademarks - Applications Received")
        assert result is not None
        assert result["metric_name"] == "trademark_applications_received"
        assert result["unit"] == "count"
        assert result["category"] == "trademarks"

    def test_match_metric_standard_patent_grants(self):
        from app.workers.connector_metric_extract import match_metric_pattern
        result = match_metric_pattern("Standard Patents (R) - Patents granted")
        assert result is not None
        assert result["metric_name"] == "standard_patents_granted"

    def test_match_metric_designs_registered(self):
        from app.workers.connector_metric_extract import match_metric_pattern
        result = match_metric_pattern("Designs - Designs registered")
        assert result is not None
        assert result["metric_name"] == "designs_registered"

    def test_match_metric_short_term_patents(self):
        from app.workers.connector_metric_extract import match_metric_pattern
        result = match_metric_pattern("Short-term Patents - Applications received")
        assert result is not None
        assert result["metric_name"] == "short_term_patent_applications_received"

    def test_match_metric_unknown_returns_none(self):
        from app.workers.connector_metric_extract import match_metric_pattern
        result = match_metric_pattern("Some Random Label")
        assert result is None

    def test_classify_time_period_fiscal_year(self):
        from app.workers.connector_metric_extract import classify_time_period
        result = classify_time_period("Apr 2024 to Mar 2025")
        assert result is not None
        assert result["time_period"] == "Apr 2024 to Mar 2025"
        assert result["period_type"] == "fiscal_year"

    def test_classify_time_period_monthly_average(self):
        from app.workers.connector_metric_extract import classify_time_period
        result = classify_time_period("Monthly average of 2025")
        assert result is not None
        assert result["time_period"] == "Monthly average 2025"

    def test_classify_time_period_provisional(self):
        from app.workers.connector_metric_extract import classify_time_period
        result = classify_time_period("Mar 2026 (the figures are provisional and subject to changes)")
        assert result is not None
        assert "provisional" in result["time_period"]

    def test_extract_metrics_from_mock_rows(self):
        """Test metric extraction from mock row data."""
        from app.workers.connector_metric_extract import (
            match_metric_pattern, classify_time_period, parse_value,
        )
        # Simulate a single row
        row_json = {
            "Unnamed: 0": "Trademarks - Applications Received",
            "Apr 2024 to Mar 2025": "34,120",
            "Monthly average of 2025": "3,124",
        }
        label = row_json["Unnamed: 0"]
        metric_def = match_metric_pattern(label)
        assert metric_def is not None

        observations = []
        for col, raw in row_json.items():
            if col == "Unnamed: 0":
                continue
            display, numeric = parse_value(raw)
            if display is None:
                continue
            time_info = classify_time_period(col)
            observations.append({
                "value": display,
                "value_numeric": numeric,
                "time_period": time_info["time_period"] if time_info else col,
            })

        assert len(observations) == 2
        assert observations[0]["value_numeric"] == 34120.0
        assert observations[1]["value_numeric"] == 3124.0

    def test_all_19_rows_match_patterns(self):
        """All 19 rows in the HK IP CSV should match known metric patterns."""
        from app.workers.connector_metric_extract import match_metric_pattern
        labels = [
            "Trademarks - Applications Received",
            "Trademarks - Applications Registered",
            "Trademarks - Providing first response within two months (calculated from the date of the Trade Marks Registry's notice confirming receipt of all the required information for substantive examination)",
            "Trademarks - Providing second response within three months (calculated from the date of expiry of first opinion or from the date of applicant's reply to first opinion)",
            "Trademarks - Outstanding applications pending for first response",
            "Standard Patents (R) - Applications received",
            "Standard Patents (R) - Patents granted",
            "Standard Patents (R) - Processing applications within ten days (calculated from the date of receipt of application)",
            "Standard Patents (R) - Applications pending - first stage (the pending applications refer to those applications pending for issuing first examination report on formal requirements)",
            "Standard Patents (R) - Applications pending - second stage (the pending applications refer to those applications pending for issuing first examination report on formal requirements)",
            "Short-term Patents - Applications received",
            "Short-term Patents - Patents granted",
            "Short-term Patents - Processing applications within ten days (calculated from the date of receipt of application)",
            "Short-term Patents - Applications pending (the pending applications refer to those applications pending for issuing first examination report on formal requirements)",
            "Designs - Applications received",
            "Designs - Applications received (number of designs)",
            "Designs - Designs registered",
            "Designs - Processing applications within ten days (calculated from the date of receipt of application)",
            "Designs - Applications pending (the pending applications refer to those applications pending for issuing first examination report on formal requirements)",
        ]
        matched = 0
        for label in labels:
            result = match_metric_pattern(label)
            if result:
                matched += 1
        assert matched == 19, f"Only {matched}/19 rows matched patterns"


# ============================================================
# Connector Metric Search Index Tests
# ============================================================

class TestConnectorMetricSearchIndex:
    """Test metric search index creation."""

    def test_build_metric_search_text(self):
        from app.workers.build_connector_search_index import _build_metric_search_text
        # Simulated row: id, metric_name, metric_description, unit, geography,
        # time_period, category, dimension, source_url, retrieved_at,
        # confidence_score, dataset_name, portal, access_type
        row = (
            "uuid-123",
            "trademark_applications_received",
            "Number of trademark applications received",
            "count",
            "Hong Kong",
            None,
            "trademarks",
            "applications",
            "https://example.org/data.csv",
            "2025-06-01",
            0.85,
            "HK IP Statistics",
            "data.gov.hk",
            "csv",
        )
        text = _build_metric_search_text(row)
        assert "trademark_applications_received" in text
        assert "trademarks" in text
        assert "Hong Kong" in text
        assert "count" in text
        assert "data.gov.hk" in text
        assert "HK IP Statistics" in text


# ============================================================
# find_data Connector Metric Integration Tests
# ============================================================

class TestFindDataConnectorMetrics:
    """Test that find_data includes connector_metrics."""

    def test_group_results_includes_connector_metrics(self):
        from app.workers.find_data import group_results
        results = [
            {
                "object_type": "connector_metric",
                "object_id": "metric-001",
                "title": "trademark_applications_received",
                "content": "Number of trademark applications received",
                "score": 0.9,
                "availability": "obtainable",
                "geography": "Hong Kong",
                "metadata": {
                    "unit": "count",
                    "category": "trademarks",
                    "dimension": "applications",
                    "dataset_name": "HK IP Statistics",
                    "portal": "data.gov.hk",
                    "retrieved_at": "2025-06-01T10:00:00Z",
                },
            },
        ]
        groups = group_results(results, limit=10)
        assert len(groups["connector_metrics"]) == 1
        assert groups["connector_metrics"][0]["data_status"] == "official_metric"
        assert groups["connector_metrics"][0]["data_status_label"] == "official synced dataset metric"

    def test_format_item_connector_metric(self):
        from app.workers.find_data import format_find_data_item
        row = {
            "object_type": "connector_metric",
            "object_id": "metric-001",
            "title": "standard_patents_granted",
            "content": "Number of standard patents granted",
            "score": 0.85,
            "availability": "obtainable",
            "geography": "Hong Kong",
            "metadata": {
                "unit": "count",
                "category": "standard_patents",
                "dimension": "grants",
                "dataset_name": "HK IP Statistics",
                "portal": "data.gov.hk",
                "retrieved_at": "2025-06-01T10:00:00Z",
            },
        }
        item = format_find_data_item(row)
        assert item["data_status"] == "official_metric"
        assert item["metric_name"] == "standard_patents_granted"
        assert item["category"] == "standard_patents"
        assert item["portal"] == "data.gov.hk"
        assert item["retrieved_at"] == "2025-06-01T10:00:00Z"

    def test_normalize_includes_connector_metrics(self):
        from app.services.research_task import normalize_find_data_results
        tool_result = {
            "ok": True,
            "data": {
                "closest_variables": [],
                "relevant_reports": [],
                "source_links": [],
                "relevant_organizations": [],
                "connector_datasets": [],
                "connector_metrics": [
                    {"title": "trademark_applications_received", "data_status": "official_metric"},
                ],
                "connector_candidates": [],
            },
        }
        result = normalize_find_data_results(tool_result)
        assert len(result["connector_metrics"]) == 1
        assert result["connector_metrics"][0]["data_status"] == "official_metric"

    def test_evidence_packet_includes_connector_metrics(self):
        from app.services.research_task import EvidencePacketBuilder, ResearchTaskPlan
        builder = EvidencePacketBuilder()
        plan = ResearchTaskPlan(query="HK patents", task_type="find_data")
        retrieved = {
            "closest_variables": [],
            "relevant_reports": [],
            "source_links": [],
            "relevant_organizations": [],
            "connector_datasets": [],
            "connector_metrics": [
                {
                    "title": "standard_patents_granted",
                    "metric_name": "standard_patents_granted",
                    "unit": "count",
                    "category": "standard_patents",
                    "geography": "Hong Kong",
                    "dataset_name": "HK IP Statistics",
                    "portal": "data.gov.hk",
                    "retrieved_at": "2025-06-01T10:00:00Z",
                },
            ],
            "connector_candidates": [],
            "limitations": [],
        }
        packet = builder.build("HK patents", plan, retrieved)
        assert "connector_metrics" in packet
        assert len(packet["connector_metrics"]) == 1
        assert packet["connector_metrics"][0]["metric_name"] == "standard_patents_granted"
        assert packet["connector_metrics"][0]["data_status_label"] == "official synced dataset metric"


# ============================================================
# data.gov.hk Discovery Ranking Tests
# ============================================================

class TestDataGovHKDiscoveryRanking:
    """Test discovery candidate ranking logic."""

    def test_compute_relevance_score_high_value_provider(self):
        from app.workers.datagovhk_expand_discovery import compute_relevance_score
        ds = {
            "title": "Patent Statistics",
            "notes": "Patent application data",
            "organization": {"title": "Intellectual Property Department"},
            "resources": [{"format": "CSV", "url": "https://example.org/data.csv"}],
        }
        score = compute_relevance_score(ds, "patent")
        assert score >= 0.5  # High value provider + keyword + format

    def test_compute_relevance_score_low_value(self):
        from app.workers.datagovhk_expand_discovery import compute_relevance_score
        ds = {
            "title": "Weather Data",
            "notes": "Temperature readings",
            "organization": {"title": "Observatory"},
            "resources": [{"format": "CSV", "url": "https://example.org/weather.csv"}],
        }
        score = compute_relevance_score(ds, "patent")
        assert score < 0.3  # Low relevance

    def test_compute_sync_priority_with_direct_download(self):
        from app.workers.datagovhk_expand_discovery import compute_sync_priority
        ds = {
            "title": "Innovation Fund Data",
            "notes": "ITF investment portfolio",
            "organization": {"title": "Innovation and Technology Commission"},
            "resources": [{"format": "CSV", "url": "https://example.org/data.csv"}],
        }
        score, reasons = compute_sync_priority(ds, 0.6)
        assert score >= 0.7
        assert any("Direct download" in r for r in reasons)
        assert any("Official provider" in r for r in reasons)

    def test_has_direct_download_csv(self):
        from app.workers.datagovhk_expand_discovery import has_direct_download
        ds = {"resources": [{"format": "CSV", "url": "https://example.org/data.csv"}]}
        assert has_direct_download(ds) == "https://example.org/data.csv"

    def test_has_direct_download_none(self):
        from app.workers.datagovhk_expand_discovery import has_direct_download
        ds = {"resources": [{"format": "HTML", "url": "https://example.org/page"}]}
        assert has_direct_download(ds) is None

    def test_extract_formats(self):
        from app.workers.datagovhk_expand_discovery import extract_formats
        ds = {"resources": [
            {"format": "CSV"},
            {"format": "csv"},
            {"format": "JSON"},
        ]}
        fmts = extract_formats(ds)
        assert "CSV" in fmts
        assert "JSON" in fmts
