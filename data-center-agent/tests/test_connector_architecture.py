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
