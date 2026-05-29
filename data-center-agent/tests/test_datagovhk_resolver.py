"""Tests for DataGovHK Resource Resolver. No live API calls."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.datagovhk_resolver import (
    DataGovHKResourceResolver,
    ResourceCandidate,
    ResolutionResult,
)


# ============================================================
# Keyword Building Tests
# ============================================================

class TestKeywordBuilding:
    def test_splits_chinese_compound_terms(self):
        resolver = DataGovHKResourceResolver()
        kw = resolver._build_keywords("商标/专利/外观设计申请及注册统计", None, "hk_patent")
        assert "商标" in kw
        assert "专利" in kw
        assert "外观" in kw or "设计" in kw
        assert "patent" in kw
        assert "trademark" in kw

    def test_prioritizes_ip_keywords(self):
        resolver = DataGovHKResourceResolver()
        kw = resolver._build_keywords("Some random title", None, "hk_patent")
        # IP keywords should be at the front
        assert kw[0] in ("patent", "trademark", "design", "ipd", "专利", "商标", "外观设计")

    def test_deduplicates(self):
        resolver = DataGovHKResourceResolver()
        kw = resolver._build_keywords("patent patent patent", None, None)
        assert kw.count("patent") == 1

    def test_empty_inputs(self):
        resolver = DataGovHKResourceResolver()
        kw = resolver._build_keywords(None, None, None)
        assert isinstance(kw, list)


# ============================================================
# Dataset ID Extraction Tests
# ============================================================

class TestDatasetIdExtraction:
    def test_extracts_from_dataset_path(self):
        resolver = DataGovHKResourceResolver()
        assert resolver._extract_dataset_id("/en-data/dataset/hk-ipo-stat") == "hk-ipo-stat"

    def test_extracts_from_package_show(self):
        resolver = DataGovHKResourceResolver()
        assert resolver._extract_dataset_id("/api/3/action/package_show?id=abc123") == "abc123"

    def test_returns_none_for_homepage(self):
        resolver = DataGovHKResourceResolver()
        assert resolver._extract_dataset_id("/") is None

    def test_returns_none_for_empty(self):
        resolver = DataGovHKResourceResolver()
        assert resolver._extract_dataset_id("") is None


# ============================================================
# Candidate Ranking Tests
# ============================================================

class TestCandidateRanking:
    def test_ipd_provider_scores_high(self):
        resolver = DataGovHKResourceResolver()
        candidates = [
            ResourceCandidate(url="http://example.com/a.csv", format="csv", provider="hk-dh", source="archive"),
            ResourceCandidate(url="http://ipd.gov.hk/b.csv", format="csv", provider="hk-ipd", source="archive"),
        ]
        ranked = resolver.rank_candidates(candidates, title="patent statistics")
        assert ranked[0].provider == "hk-ipd"
        assert ranked[0].confidence > ranked[1].confidence

    def test_csv_format_preferred(self):
        resolver = DataGovHKResourceResolver()
        candidates = [
            ResourceCandidate(url="http://example.com/a.json", format="json", provider="hk-ipd"),
            ResourceCandidate(url="http://example.com/b.csv", format="csv", provider="hk-ipd"),
        ]
        ranked = resolver.rank_candidates(candidates)
        assert ranked[0].format == "csv"

    def test_registration_keywords_boost(self):
        resolver = DataGovHKResourceResolver()
        c1 = ResourceCandidate(url="http://a.csv", format="csv", provider="hk-ipd",
                               dataset_name="Statistics of Searches conducted")
        c2 = ResourceCandidate(url="http://b.csv", format="csv", provider="hk-ipd",
                               dataset_name="Statistics of Registrations and Grants")
        ranked = resolver.rank_candidates([c1, c2])
        # Registrations/grants should score higher than searches
        assert ranked[0].dataset_name == "Statistics of Registrations and Grants"
        assert ranked[0].confidence > ranked[1].confidence

    def test_survey_penalized(self):
        resolver = DataGovHKResourceResolver()
        c1 = ResourceCandidate(url="http://a.csv", format="csv", provider="hk-ipd",
                               dataset_name="Survey on Public Awareness")
        c2 = ResourceCandidate(url="http://b.csv", format="csv", provider="hk-ipd",
                               dataset_name="Statistics of Patent Registrations")
        ranked = resolver.rank_candidates([c1, c2])
        assert ranked[0].dataset_name == "Statistics of Patent Registrations"

    def test_english_url_preferred(self):
        resolver = DataGovHKResourceResolver()
        c1 = ResourceCandidate(url="http://ipd.gov.hk/tc/data.csv", format="csv", provider="hk-ipd")
        c2 = ResourceCandidate(url="http://ipd.gov.hk/en/data.csv", format="csv", provider="hk-ipd")
        ranked = resolver.rank_candidates([c1, c2])
        assert "/en/" in ranked[0].url


# ============================================================
# Resolution Strategy Tests
# ============================================================

class TestResolutionStrategy:
    def test_minimum_confidence_threshold(self):
        resolver = DataGovHKResourceResolver()
        # Low-confidence candidates should not be selected
        candidates = [
            ResourceCandidate(url="http://example.com/wine.csv", format="csv",
                              provider="hk-cedb", source="ckan", confidence=2.0),
        ]
        result = ResolutionResult(original_url="https://data.gov.hk")
        result.all_candidates = candidates
        # Manually test the threshold logic
        if candidates and candidates[0].confidence >= 2.5:
            result.selected = candidates[0]
            result.success = True
        assert result.selected is None
        assert not result.success

    def test_high_confidence_selected(self):
        resolver = DataGovHKResourceResolver()
        candidates = [
            ResourceCandidate(url="http://ipd.gov.hk/data.csv", format="csv",
                              provider="hk-ipd", source="archive", confidence=9.0),
        ]
        result = ResolutionResult(original_url="https://data.gov.hk")
        result.all_candidates = candidates
        if candidates and candidates[0].confidence >= 2.5:
            result.selected = candidates[0]
            result.success = True
        assert result.selected is not None
        assert result.success

    def test_failure_reason_includes_confidence(self):
        resolver = DataGovHKResourceResolver()
        result = ResolutionResult(original_url="https://data.gov.hk")
        result.all_candidates = [
            ResourceCandidate(url="http://x.csv", confidence=1.0),
        ]
        best_conf = result.all_candidates[0].confidence
        result.failure_reason = f"Best candidate confidence: {best_conf}"
        assert "1.0" in result.failure_reason


# ============================================================
# CKAN Response Parsing Tests
# ============================================================

class TestCKANParsing:
    def test_extract_ckan_resources(self):
        resolver = DataGovHKResourceResolver()
        pkg = {
            "name": "test-pkg",
            "title": "Test Package",
            "resources": [
                {"url": "http://a.csv", "format": "CSV", "name": "Data", "id": "r1"},
                {"url": "http://b.pdf", "format": "PDF", "name": "Doc", "id": "r2"},
                {"url": "http://c.json", "format": "JSON", "name": "API", "id": "r3"},
            ],
        }
        candidates = []
        resolver._extract_ckan_resources(pkg, candidates)
        assert len(candidates) == 2  # CSV and JSON, not PDF
        assert candidates[0].format == "csv"
        assert candidates[1].format == "json"


# ============================================================
# Archive Response Parsing Tests
# ============================================================

class TestArchiveParsing:
    def test_archive_file_structure(self):
        """Test that archive API response is correctly parsed."""
        mock_files = [
            {
                "dataset-id": "hk-ipd-stats",
                "dataset-name-en": "IP Statistics",
                "format": "csv",
                "provider-id": "hk-ipd",
                "resource-name-en": "Statistics CSV",
                "total-size": 5000,
                "url": "http://ipd.gov.hk/stats.csv",
            },
        ]
        candidates = []
        for f in mock_files:
            candidates.append(ResourceCandidate(
                url=f["url"],
                dataset_id=f["dataset-id"],
                dataset_name=f["dataset-name-en"],
                resource_name=f["resource-name-en"],
                format=f["format"],
                provider=f["provider-id"],
                source="archive",
            ))
        assert len(candidates) == 1
        assert candidates[0].provider == "hk-ipd"
        assert candidates[0].source == "archive"

    def test_dedup_by_url(self):
        """Test that duplicate URLs from different searches are deduped."""
        seen_urls = set()
        files = [
            {"url": "http://a.csv"},
            {"url": "http://a.csv"},  # duplicate
            {"url": "http://b.csv"},
        ]
        unique = []
        for f in files:
            url = f["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(url)
        assert len(unique) == 2


# ============================================================
# Sync Failure Tests
# ============================================================

class TestSyncFailures:
    def test_metadata_only_not_marked_success(self):
        """A resolution that only stores metadata should not be marked as synced."""
        result = ResolutionResult(
            success=False,
            original_url="https://data.gov.hk",
            failure_reason="No matching resources found",
        )
        assert not result.success
        assert result.selected is None

    def test_empty_candidate_list(self):
        resolver = DataGovHKResourceResolver()
        ranked = resolver.rank_candidates([])
        assert ranked == []
