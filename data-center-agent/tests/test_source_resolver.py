import httpx

from app.agents.source_resolver import SourceResolver, verify_artifact_url


def test_discovers_relative_pdf_link() -> None:
    html = '<a href="/files/report.pdf">Download PDF</a>'

    artifacts = SourceResolver().discover_artifacts(html, "https://example.gov/reports/landing")

    assert artifacts[0].url == "https://example.gov/files/report.pdf"
    assert artifacts[0].artifact_type == "pdf"
    assert artifacts[0].score >= 100


def test_verifies_download_report_link_as_pdf_from_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    verification = verify_artifact_url("https://example.gov/download?id=123", client=client)

    assert verification.artifact_type == "pdf"
    assert verification.is_downloadable is True


def test_verify_falls_back_to_get_when_head_is_forbidden() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(403, request=request)
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    verification = verify_artifact_url("https://example.gov/report.pdf", client=client)

    assert verification.status_code == 200
    assert verification.artifact_type == "pdf"
    assert verification.is_downloadable is True


def test_discovers_dataset_links() -> None:
    html = """
    <a href="/data/table.csv">Download data</a>
    <a href="/data/workbook.xlsx">Workbook</a>
    """

    artifacts = SourceResolver().discover_artifacts(html, "https://example.gov/report")

    assert [artifact.artifact_type for artifact in artifacts[:2]] == ["dataset_file", "dataset_file"]


def test_report_pdf_beats_navigation_links() -> None:
    html = """
    <a href="/about">About</a>
    <a href="/contact">Contact</a>
    <a href="/privacy">Privacy</a>
    <a href="/uploads/venture-report.pdf">Read the full report</a>
    """

    artifacts = SourceResolver().discover_artifacts(html, "https://example.gov")

    assert artifacts[0].url == "https://example.gov/uploads/venture-report.pdf"
    assert artifacts[0].artifact_type == "pdf"


def test_pdf_text_without_href_has_no_artifact() -> None:
    html = "<main>Download PDF for the full report when available.</main>"

    artifacts = SourceResolver().discover_artifacts(html, "https://example.gov/report")
    signals = SourceResolver().inspect_html(html)

    assert artifacts == []
    assert signals.status == "unresolved"


def test_form_or_button_without_href_needs_browser_or_gated() -> None:
    html = """
    <form><input type="email" name="email"><button>Download report</button></form>
    <a href="#">Download PDF</a>
    """

    signals = SourceResolver().inspect_html(html)

    assert signals.status == "gated_or_paywalled"
    assert signals.email_field_count >= 1
