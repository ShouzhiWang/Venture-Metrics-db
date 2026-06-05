"""Tests for source_reader and table_analyzer — the data reading layer."""
from __future__ import annotations

import json
import io
import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# source_reader tests
# ---------------------------------------------------------------------------

class TestSourceReader:
    """Tests for read_source and its parsers."""

    def test_csv_parsing(self):
        """CSV content is parsed into a table packet."""
        from app.tools.source_reader import _parse_csv

        csv_bytes = b"country,year,value\nSingapore,2020,100\nSingapore,2021,120\nHong Kong,2020,80\n"
        result = _parse_csv(csv_bytes, title="Test CSV", source_url="https://example.com/data.csv", retrieved_at="2025-01-01", max_rows=500)

        assert result["packet_type"] == "table"
        assert result["title"] == "Test CSV"
        assert result["row_count"] == 3
        assert result["column_count"] == 3
        assert result["evidence_level"] == "table_values_read"
        col_names = [c["name"] for c in result["columns"]]
        assert "country" in col_names
        assert "year" in col_names
        assert "value" in col_names
        assert len(result["rows_sample"]) == 3

    def test_tsv_parsing(self):
        """TSV content is parsed into a table packet."""
        from app.tools.source_reader import _parse_csv

        tsv_bytes = b"name\tcount\nA\t10\nB\t20\n"
        result = _parse_csv(tsv_bytes, title="Test TSV", source_url="https://example.com/data.tsv", retrieved_at="2025-01-01", max_rows=500, delimiter="\t")

        assert result["packet_type"] == "table"
        assert result["row_count"] == 2
        col_names = [c["name"] for c in result["columns"]]
        assert "name" in col_names
        assert "count" in col_names

    def test_xlsx_parsing(self):
        """XLSX content is parsed into a table packet."""
        from app.tools.source_reader import _parse_xlsx
        import pandas as pd

        # Create a simple XLSX in memory
        df = pd.DataFrame({"metric": ["GDP", "R&D"], "value_2020": [100, 50], "value_2021": [110, 55]})
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        xlsx_bytes = buf.getvalue()

        result = _parse_xlsx(xlsx_bytes, title="Test XLSX", source_url="https://example.com/data.xlsx", retrieved_at="2025-01-01", max_rows=500)

        assert result["packet_type"] == "table"
        assert result["row_count"] == 2
        assert result["column_count"] == 3
        col_names = [c["name"] for c in result["columns"]]
        assert "metric" in col_names

    def test_json_array_parsing(self):
        """JSON array of objects is parsed into a table packet."""
        from app.tools.source_reader import _parse_json

        data = [
            {"country": "Singapore", "year": 2020, "value": 100},
            {"country": "Singapore", "year": 2021, "value": 120},
        ]
        result = _parse_json(json.dumps(data).encode(), title="Test JSON", source_url="https://example.com/api", retrieved_at="2025-01-01", max_rows=500)

        assert result["packet_type"] == "table"
        assert result["row_count"] == 2
        col_names = [c["name"] for c in result["columns"]]
        assert "country" in col_names

    def test_json_nested_parsing(self):
        """JSON with nested data key is parsed correctly."""
        from app.tools.source_reader import _parse_json

        data = {"data": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}
        result = _parse_json(json.dumps(data).encode(), title="Nested JSON", source_url="https://example.com/api", retrieved_at="2025-01-01", max_rows=500)

        assert result["packet_type"] == "table"
        assert result["row_count"] == 2

    def test_html_table_parsing(self):
        """HTML table is parsed into a table packet."""
        from app.tools.source_reader import _parse_html_table

        html = """
        <html><body>
        <table>
        <tr><th>Country</th><th>GDP</th></tr>
        <tr><td>Singapore</td><td>340B</td></tr>
        <tr><td>Hong Kong</td><td>360B</td></tr>
        </table>
        </body></html>
        """
        result = _parse_html_table(html, title="HTML Table", source_url="https://example.com/page", retrieved_at="2025-01-01", max_rows=500)

        assert result["packet_type"] == "table"
        assert result["row_count"] == 2

    def test_pdf_parsing(self):
        """PDF content is parsed into a text packet."""
        from app.tools.source_reader import _parse_pdf
        import fitz

        # Create a simple PDF in memory
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Singapore GDP grew 3.5% in 2023.")
        pdf_bytes = doc.tobytes()
        doc.close()

        result = _parse_pdf(pdf_bytes, title="Test PDF", source_url="https://example.com/report.pdf", retrieved_at="2025-01-01")

        assert result["packet_type"] == "text"
        assert result["evidence_level"] == "text_evidence_read"
        assert len(result["chunks"]) > 0
        assert "Singapore" in result["chunks"][0]["text"]

    def test_metadata_only_for_unfetchable_url(self):
        """Unfetchable URL returns metadata_only packet."""
        from app.tools.source_reader import _fetch_and_parse

        result = _fetch_and_parse(
            url="https://this-domain-does-not-exist-12345.com/data.csv",
            title="Missing Source",
            content_type_hint="",
            max_rows=500,
            timeout=3,
        )
        assert result["packet_type"] == "metadata_only"
        assert "Fetch failed" in result.get("reason", "")

    def test_detect_format_by_extension(self):
        """Format detection works by URL extension."""
        from app.tools.source_reader import _detect_format

        assert _detect_format("https://example.com/data.csv", "", b"") == "csv"
        assert _detect_format("https://example.com/data.tsv", "", b"") == "tsv"
        assert _detect_format("https://example.com/data.xlsx", "", b"") == "xlsx"
        assert _detect_format("https://example.com/data.json", "", b"") == "json"
        assert _detect_format("https://example.com/report.pdf", "", b"") == "pdf"
        assert _detect_format("https://example.com/page.html", "", b"") == "html_table"

    def test_detect_format_by_magic_bytes(self):
        """Format detection works by magic bytes."""
        from app.tools.source_reader import _detect_format

        assert _detect_format("https://example.com/download", "", b"PK\x03\x04") == "xlsx"
        assert _detect_format("https://example.com/download", "", b"%PDF-1.4") == "pdf"
        assert _detect_format("https://example.com/download", "", b'{"data": []}') == "json"

    def test_is_data_url(self):
        """URL classification for downloadable data."""
        from web.backend.routes.chat import _is_data_url

        assert _is_data_url("https://example.com/data.csv") is True
        assert _is_data_url("https://example.com/data.xlsx") is True
        assert _is_data_url("https://example.com/api/data.json") is True
        assert _is_data_url("https://data.gov.sg/resource/abc/download/data.csv") is True
        assert _is_data_url("https://example.com/about-us") is False


# ---------------------------------------------------------------------------
# table_analyzer tests
# ---------------------------------------------------------------------------

class TestTableAnalyzer:
    """Tests for analyze_table_for_query."""

    def _make_table_packet(self, columns, rows, title="Test Table"):
        return {
            "packet_type": "table",
            "title": title,
            "source_url": "https://example.com/data.csv",
            "retrieved_at": "2025-01-01",
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": [
                {"name": c, "dtype": "int64" if c in ("value", "amount") else "object", "non_null_count": len(rows), "sample_values": [str(r.get(c, "")) for r in rows[:3]]}
                for c in columns
            ],
            "rows_sample": rows,
            "evidence_level": "table_values_read",
        }

    def test_heuristic_mapping_finds_time_and_metric(self):
        """Heuristic column mapping detects year and value columns."""
        from app.tools.table_analyzer import _heuristic_column_mapping

        columns = [
            {"name": "country", "dtype": "object", "non_null_count": 5, "sample_values": ["Singapore", "Hong Kong"]},
            {"name": "year", "dtype": "int64", "non_null_count": 5, "sample_values": ["2020", "2021", "2022"]},
            {"name": "gdp_value", "dtype": "float64", "non_null_count": 5, "sample_values": ["340.5", "360.2"]},
        ]
        result = _heuristic_column_mapping("GDP trends by country", columns, [])

        assert result["time_column"] == "year"
        assert result["geography_column"] == "country"
        assert "gdp_value" in result["metric_columns"]

    def test_compute_from_mapping_aggregations(self):
        """Python computation produces correct aggregations."""
        from app.tools.table_analyzer import _compute_from_mapping

        table = self._make_table_packet(
            ["country", "year", "value"],
            [
                {"country": "Singapore", "year": "2020", "value": "100"},
                {"country": "Singapore", "year": "2021", "value": "120"},
                {"country": "Hong Kong", "year": "2020", "value": "80"},
            ],
        )
        mapping = {
            "time_column": "year",
            "geography_column": "country",
            "metric_columns": ["value"],
            "dimension_columns": [],
            "filters": {},
            "relevance": "direct",
        }
        result = _compute_from_mapping("GDP trends", table, mapping)

        assert "aggregations" in result
        assert "value" in result["aggregations"]
        assert result["aggregations"]["value"]["sum"] == 300
        assert result["aggregations"]["value"]["mean"] == 100

    def test_compute_from_mapping_time_series(self):
        """Python computation produces time series when year column exists."""
        from app.tools.table_analyzer import _compute_from_mapping

        table = self._make_table_packet(
            ["year", "amount"],
            [
                {"year": "2020", "amount": "100"},
                {"year": "2021", "amount": "150"},
                {"year": "2022", "amount": "200"},
            ],
        )
        mapping = {
            "time_column": "year",
            "geography_column": None,
            "metric_columns": ["amount"],
            "dimension_columns": [],
            "filters": {},
            "relevance": "direct",
        }
        result = _compute_from_mapping("funding trends", table, mapping)

        assert "time_series" in result
        assert "amount" in result["time_series"]
        assert "2020" in result["time_series"]["amount"]
        assert result["time_series"]["amount"]["2020"]["mean"] == 100

    def test_compute_with_filter(self):
        """Python computation applies filters correctly."""
        from app.tools.table_analyzer import _compute_from_mapping

        table = self._make_table_packet(
            ["country", "year", "value"],
            [
                {"country": "Singapore", "year": "2020", "value": "100"},
                {"country": "Singapore", "year": "2021", "value": "120"},
                {"country": "Hong Kong", "year": "2020", "value": "80"},
                {"country": "Hong Kong", "year": "2021", "value": "90"},
            ],
        )
        mapping = {
            "time_column": "year",
            "geography_column": "country",
            "metric_columns": ["value"],
            "dimension_columns": [],
            "filters": {"country": "Singapore"},
            "relevance": "direct",
        }
        result = _compute_from_mapping("Singapore funding", table, mapping)

        assert result["filtered_row_count"] == 2
        assert result["aggregations"]["value"]["sum"] == 220

    def test_non_table_returns_metadata_only(self):
        """Non-table packet returns metadata_only."""
        from app.tools.table_analyzer import analyze_table_for_query

        result = analyze_table_for_query("test query", {"packet_type": "text", "chunks": []})
        assert result["can_answer"] is False
        assert result["evidence_level"] == "metadata_only"

    def test_full_integration_csv_to_analysis(self):
        """End-to-end: CSV bytes → table packet → analysis → computed values."""
        from app.tools.source_reader import _parse_csv
        from app.tools.table_analyzer import analyze_table_for_query

        csv_bytes = (
            b"country,year,vc_funding_usd\n"
            b"Singapore,2020,1500000000\n"
            b"Singapore,2021,2100000000\n"
            b"Singapore,2022,1800000000\n"
            b"Hong Kong,2020,900000000\n"
            b"Hong Kong,2021,1200000000\n"
        )
        table = _parse_csv(csv_bytes, title="VC Funding", source_url="https://example.com/vc.csv", retrieved_at="2025-01-01", max_rows=500)

        assert table["packet_type"] == "table"
        assert table["row_count"] == 5

        analysis = analyze_table_for_query("Singapore VC funding trends", table)

        assert analysis["can_answer"] is True
        assert analysis["evidence_level"] == "table_values_read"
        # Heuristic mapping doesn't auto-filter — all rows are included
        assert analysis["computed_results"]["filtered_row_count"] == 5
        assert "vc_funding_usd" in analysis["computed_results"]["aggregations"]
        # Time series should be present
        assert "time_series" in analysis["computed_results"]

    def test_guardrail_irrelevant_table_not_used_as_evidence(self):
        """When table lacks relevant columns, analysis returns low confidence or can_answer=False."""
        from app.tools.source_reader import _parse_csv
        from app.tools.table_analyzer import analyze_table_for_query

        csv_bytes = (
            b"university_name,city\n"
            b"NUS,Singapore\n"
            b"HKUST,Hong Kong\n"
        )
        table = _parse_csv(csv_bytes, title="University Directory", source_url="https://example.com/uni.csv", retrieved_at="2025-01-01", max_rows=500)

        analysis = analyze_table_for_query("Singapore VC funding 2020-2024", table)

        # Table has no numeric columns — should not be able to answer
        assert analysis["can_answer"] is False
