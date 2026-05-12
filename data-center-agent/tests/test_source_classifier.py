from app.agents.source_classifier import classify_source


def test_classifies_pdf_url() -> None:
    result = classify_source("https://example.gov/report.pdf")

    assert result["source_type"] == "pdf"
    assert result["detected_format"] == "pdf"
    assert result["access_type"] == "public"


def test_classifies_csv_query() -> None:
    result = classify_source("https://example.gov/download?format=csv")

    assert result["source_type"] == "csv"


def test_defaults_http_to_html() -> None:
    result = classify_source("https://example.gov/report")

    assert result["source_type"] == "html"


def test_classifies_excel_url() -> None:
    result = classify_source("https://example.gov/data/workbook.xlsx")

    assert result["source_type"] == "xlsx"
    assert result["detected_format"] == "xlsx"
