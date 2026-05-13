from pathlib import Path

import pytest

from app.agents.parser import (
    OCRDependencyError,
    OCREngine,
    PaddleOCREngine,
    ParsedDocument,
    ParsedPage,
    assess_pdf_text_quality,
    build_chunks,
    chunk_text_by_tokens,
    parse_raw_file,
    parsed_json,
)


def test_chunk_text_by_tokens_creates_target_sized_chunks() -> None:
    text = " ".join(f"word{i}" for i in range(2500))

    chunks = chunk_text_by_tokens(text)

    assert len(chunks) == 3
    assert all(800 <= len(chunk.split()) <= 1200 for chunk in chunks[:-1])


def test_parse_html_extracts_text_and_table_metadata(tmp_path: Path) -> None:
    html_path = tmp_path / "report.html"
    html_path.write_text(
        """
        <html>
          <head><title>Labor Report</title></head>
          <body>
            <h1>Labor Report</h1>
            <p>Methodology: employment rate is defined as employed workers divided by labor force.</p>
            <table><caption>Indicators</caption><tr><th>Name</th><th>Value</th></tr><tr><td>Employment</td><td>60%</td></tr></table>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    parsed = parse_raw_file(html_path, "html", "text/html")
    chunks = build_chunks("report-1", parsed)

    assert "employment rate" in parsed.text.lower()
    assert parsed.metadata["html_table_count"] == 1
    assert "Labor Report" in parsed_json(parsed)
    assert chunks[0]["page_number"] is None
    assert chunks[0]["metadata"]["table_placeholders"][0]["kind"] == "html_table"


def test_low_text_pdf_quality_recommends_ocr() -> None:
    pages = [
        ParsedPage(page_number=1, text="", extraction_method="pymupdf"),
        ParsedPage(page_number=2, text="Page 2", extraction_method="pymupdf"),
        ParsedPage(page_number=3, text="", extraction_method="pymupdf"),
    ]

    quality = assess_pdf_text_quality(pages)

    assert quality.ocr_recommended is True
    assert quality.total_characters < 500
    assert quality.empty_page_ratio > 0.3
    assert "too_many_empty_pages" in quality.reason


def test_normal_text_pdf_quality_does_not_recommend_ocr() -> None:
    long_text = " ".join("economic report data" for _ in range(150))
    pages = [
        ParsedPage(page_number=1, text=long_text, extraction_method="pymupdf"),
        ParsedPage(page_number=2, text=long_text, extraction_method="pymupdf"),
    ]

    quality = assess_pdf_text_quality(pages)

    assert quality.ocr_recommended is False
    assert quality.reason == "text_extraction_quality_acceptable"


def test_paddleocr_missing_dependency_raises_clear_error(monkeypatch) -> None:
    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "paddleocr":
            raise ImportError("No module named paddleocr")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(OCRDependencyError, match="PaddleOCR is not installed"):
        PaddleOCREngine()


def test_build_chunks_preserves_ocr_metadata() -> None:
    class FakeOCREngine(OCREngine):
        def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
            return [
                ParsedPage(
                    page_number=1,
                    text=" ".join("recognized text" for _ in range(500)),
                    extraction_method="ocr",
                    metadata={"ocr_engine": "fake", "confidence": 0.91, "is_scanned_pdf": True},
                )
            ]

    pages = FakeOCREngine().extract_pages(Path("fake.pdf"))
    parsed = ParsedDocument(text=pages[0].text, pages=pages, metadata={"parser": "ocr"})
    chunks = build_chunks("report-1", parsed)

    assert chunks[0]["page_number"] == 1
    assert chunks[0]["metadata"]["page_extraction_method"] == "ocr"
    assert chunks[0]["metadata"]["ocr_engine"] == "fake"
    assert chunks[0]["metadata"]["is_scanned_pdf"] is True


def test_pdf_pipeline_uses_mock_ocr_when_text_quality_is_low(monkeypatch, tmp_path: Path) -> None:
    from app.agents import parser

    class FakeOCREngine(OCREngine):
        def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
            return [
                ParsedPage(
                    page_number=1,
                    text=" ".join("ocr recovered report text" for _ in range(120)),
                    extraction_method="ocr",
                    metadata={"ocr_engine": "fake", "confidence": 0.88, "is_scanned_pdf": True},
                )
            ]

    monkeypatch.setattr(
        parser,
        "_extract_pdf_with_pymupdf",
        lambda path: [ParsedPage(page_number=1, text="", extraction_method="pymupdf")],
    )
    monkeypatch.setattr(
        parser,
        "_extract_pdf_with_pdfplumber",
        lambda path: [ParsedPage(page_number=1, text="", extraction_method="pdfplumber")],
    )

    parsed = parser.extract_text_from_pdf(tmp_path / "scanned.pdf", ocr_engine=FakeOCREngine())

    assert parsed.metadata["parser"] == "ocr"
    assert parsed.metadata["ocr_engine"] == "custom"
    assert parsed.pages[0].extraction_method == "ocr"
    assert parsed.pages[0].metadata["confidence"] == 0.88
