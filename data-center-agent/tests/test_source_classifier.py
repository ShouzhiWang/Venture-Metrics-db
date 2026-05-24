from app.agents.ecosystem_org_extractor import classify_source_route
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
    assert result["source_route"] == "landing_page"


def test_classifies_excel_url() -> None:
    result = classify_source("https://example.gov/data/workbook.xlsx")

    assert result["source_type"] == "xlsx"
    assert result["detected_format"] == "xlsx"
    assert result["source_route"] == "dataset"


def test_classifies_pdf_route() -> None:
    result = classify_source("https://example.gov/report.pdf")

    assert result["source_route"] == "report_pdf"


def test_classifies_organization_homepage_route_from_html() -> None:
    html = """
    <html>
      <head><title>Singapore FinTech Association</title></head>
      <body><p>About us: we support startup founders, investors, and ecosystem members in Singapore.</p></body>
    </html>
    """

    result = classify_source_route(url="https://example.org", source_type="html", html=html)

    assert result.source_route == "ecosystem_organization"
