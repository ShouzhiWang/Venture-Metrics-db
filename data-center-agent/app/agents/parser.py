import json
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import pdfplumber
import trafilatura
from bs4 import BeautifulSoup

from app.utils.text import count_tokens_rough, normalize_whitespace


PDF_FALLBACK_MIN_CHARS = 500
DEFAULT_TARGET_TOKENS = 1000
DEFAULT_MIN_TOKENS = 800
DEFAULT_MAX_TOKENS = 1200
EMPTY_PAGE_MAX_CHARS = 25
MIN_AVG_CHARS_PER_PAGE = 100
MAX_EMPTY_PAGE_RATIO = 0.30


class OCRDependencyError(RuntimeError):
    """Raised when OCR is requested but the configured OCR dependency is unavailable."""


@dataclass
class ParsedPage:
    page_number: int | None
    text: str
    extraction_method: str
    tables: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionQuality:
    total_characters: int
    average_characters_per_page: float
    empty_page_ratio: float
    ocr_recommended: bool
    reason: str


class OCREngine(ABC):
    @abstractmethod
    def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
        raise NotImplementedError


class PaddleOCREngine(OCREngine):
    def __init__(self, language: str = "en", dpi: int = 200):
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OCRDependencyError(
                "PaddleOCR is not installed. Install OCR support with: pip install -e '.[ocr]'"
            ) from exc

        self.language = language
        self.dpi = dpi
        self._ocr = PaddleOCR(lang=language)

    def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        zoom = self.dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        with fitz.open(pdf_path) as document, tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for index, page in enumerate(document, start=1):
                image_path = temp_root / f"page-{index}.png"
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(image_path)
                try:
                    ocr_result = self._ocr.ocr(str(image_path), cls=True)
                except TypeError:
                    # New PaddleOCR API — use predict() instead
                    ocr_result = list(self._ocr.predict(str(image_path)))
                text, confidence = _parse_paddleocr_result(ocr_result)
                pages.append(
                    ParsedPage(
                        page_number=index,
                        text=normalize_whitespace(text),
                        extraction_method="ocr",
                        tables=detect_table_placeholders(text),
                        metadata={
                            "ocr_engine": "paddleocr",
                            "confidence": confidence,
                            "is_scanned_pdf": True,
                            "dpi": self.dpi,
                            "language": self.language,
                        },
                    )
                )
        return pages


class TesseractOCREngine(OCREngine):
    """OCR engine using Tesseract (tesseract-ocr system package)."""

    LANG_MAP = {
        "en": "eng",
        "ch": "chi_sim",
        "zh": "chi_sim",
        "chinese_cht": "chi_tra",
    }

    def __init__(self, language: str = "en", dpi: int = 200):
        try:
            import pytesseract  # noqa: F401
        except ImportError as exc:
            raise OCRDependencyError(
                "pytesseract is not installed. Install with: pip install pytesseract"
            ) from exc

        self.language = language
        self.dpi = dpi
        self._tess_lang = self.LANG_MAP.get(language, language)

    def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
        import pytesseract
        pages: list[ParsedPage] = []
        zoom = self.dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        with fitz.open(pdf_path) as document, tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for index, page in enumerate(document, start=1):
                image_path = temp_root / f"page-{index}.png"
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(image_path)
                text = pytesseract.image_to_string(str(image_path), lang=self._tess_lang)
                pages.append(
                    ParsedPage(
                        page_number=index,
                        text=normalize_whitespace(text),
                        extraction_method="ocr",
                        tables=detect_table_placeholders(text),
                        metadata={
                            "ocr_engine": "tesseract",
                            "is_scanned_pdf": True,
                            "dpi": self.dpi,
                            "language": self.language,
                        },
                    )
                )
        return pages


@dataclass
class ParsedDocument:
    text: str
    pages: list[ParsedPage]
    metadata: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {
                "text_length": len(self.text),
                "page_count": len(self.pages),
                "metadata": self.metadata,
                "pages": [
                    {
                        "page_number": page.page_number,
                        "text_length": len(page.text),
                        "extraction_method": page.extraction_method,
                        "tables": page.tables,
                        "metadata": page.metadata,
                    }
                    for page in self.pages
                ],
            },
            ensure_ascii=True,
            indent=2,
        )


def extract_title_from_html(content: bytes) -> str | None:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(strip=True)
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else None


def extract_text_from_pdf(path: Path, ocr_engine: OCREngine | None = None) -> ParsedDocument:
    pymupdf_pages = _extract_pdf_with_pymupdf(path)
    pymupdf_text = _join_page_text(pymupdf_pages)
    pymupdf_quality = assess_pdf_text_quality(pymupdf_pages)

    if pymupdf_quality.ocr_recommended:
        pdfplumber_pages = _extract_pdf_with_pdfplumber(path)
        pdfplumber_text = _join_page_text(pdfplumber_pages)
        pdfplumber_quality = assess_pdf_text_quality(pdfplumber_pages)
        if not pdfplumber_quality.ocr_recommended or len(pdfplumber_text) > len(pymupdf_text):
            if not pdfplumber_quality.ocr_recommended:
                return ParsedDocument(
                    text=pdfplumber_text,
                    pages=pdfplumber_pages,
                    metadata={
                        "parser": "pdfplumber",
                        "fallback_from": "pymupdf",
                        "fallback_reason": pymupdf_quality.reason,
                        "pymupdf_quality": _quality_metadata(pymupdf_quality),
                        "pdfplumber_quality": _quality_metadata(pdfplumber_quality),
                    },
                )
            best_text_pages = pdfplumber_pages
            best_text = pdfplumber_text
            best_text_parser = "pdfplumber"
            best_quality = pdfplumber_quality
        else:
            best_text_pages = pymupdf_pages
            best_text = pymupdf_text
            best_text_parser = "pymupdf"
            best_quality = pymupdf_quality

        if best_quality.ocr_recommended:
            engine = ocr_engine
            if engine is None:
                try:
                    engine = PaddleOCREngine()
                except Exception:
                    try:
                        engine = TesseractOCREngine()
                    except Exception:
                        pass
            if engine is None:
                # No OCR engine available — return best text-based result
                return ParsedDocument(
                    text=best_text,
                    pages=best_text_pages,
                    metadata={
                        "parser": best_text_parser,
                        "ocr_attempted": False,
                        "ocr_error": "No OCR engine available (PaddleOCR and Tesseract both failed)",
                        "is_scanned_pdf": True,
                        "pymupdf_quality": _quality_metadata(pymupdf_quality),
                        "pdfplumber_quality": _quality_metadata(pdfplumber_quality),
                    },
                )
            ocr_pages = None
            ocr_engine_name = "custom" if ocr_engine else "paddleocr"
            try:
                ocr_pages = engine.extract_pages(path)
            except Exception:
                # PaddleOCR failed — try Tesseract fallback
                if not isinstance(engine, TesseractOCREngine):
                    try:
                        tess = TesseractOCREngine(language=engine.language if hasattr(engine, 'language') else "en")
                        ocr_pages = tess.extract_pages(path)
                        ocr_engine_name = "tesseract"
                    except Exception:
                        pass
            if ocr_pages is None:
                return ParsedDocument(
                    text=best_text,
                    pages=best_text_pages,
                    metadata={
                        "parser": best_text_parser,
                        "ocr_attempted": True,
                        "ocr_error": "All OCR engines failed",
                        "is_scanned_pdf": True,
                        "pymupdf_quality": _quality_metadata(pymupdf_quality),
                        "pdfplumber_quality": _quality_metadata(pdfplumber_quality),
                    },
                )
            ocr_text = _join_page_text(ocr_pages)
            ocr_quality = assess_pdf_text_quality(ocr_pages)
            return ParsedDocument(
                text=ocr_text,
                pages=ocr_pages,
                metadata={
                    "parser": "ocr",
                    "ocr_engine": ocr_engine_name if not ocr_engine else "custom",
                    "fallback_from": best_text_parser,
                    "fallback_reason": best_quality.reason,
                    "is_scanned_pdf": True,
                    "pymupdf_quality": _quality_metadata(pymupdf_quality),
                    "pdfplumber_quality": _quality_metadata(pdfplumber_quality),
                    "ocr_quality": _quality_metadata(ocr_quality),
                    "pre_ocr_text_length": len(best_text),
                },
            )

    return ParsedDocument(
        text=pymupdf_text,
        pages=pymupdf_pages,
        metadata={
            "parser": "pymupdf",
            "fallback_considered": pymupdf_quality.ocr_recommended,
            "pymupdf_quality": _quality_metadata(pymupdf_quality),
        },
    )


def assess_pdf_text_quality(pages: list[ParsedPage]) -> ExtractionQuality:
    page_count = len(pages)
    total_characters = sum(len(page.text.strip()) for page in pages)
    average_characters = total_characters / page_count if page_count else 0
    empty_pages = sum(1 for page in pages if len(page.text.strip()) <= EMPTY_PAGE_MAX_CHARS)
    empty_ratio = empty_pages / page_count if page_count else 1.0

    reasons: list[str] = []
    if total_characters < PDF_FALLBACK_MIN_CHARS:
        reasons.append("total_text_too_short")
    if average_characters < MIN_AVG_CHARS_PER_PAGE:
        reasons.append("average_text_per_page_too_short")
    if empty_ratio > MAX_EMPTY_PAGE_RATIO:
        reasons.append("too_many_empty_pages")
    if not pages:
        reasons.append("no_pages_extracted")

    return ExtractionQuality(
        total_characters=total_characters,
        average_characters_per_page=average_characters,
        empty_page_ratio=empty_ratio,
        ocr_recommended=bool(reasons),
        reason=", ".join(reasons) if reasons else "text_extraction_quality_acceptable",
    )


def _extract_pdf_with_pymupdf(path: Path) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            text = normalize_whitespace(page.get_text("text"))
            tables = detect_table_placeholders(text)
            pages.append(ParsedPage(index, text, "pymupdf", tables))
    return pages


def _extract_pdf_with_pdfplumber(path: Path) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    with pdfplumber.open(path) as document:
        for index, page in enumerate(document.pages, start=1):
            text = normalize_whitespace(page.extract_text() or "")
            tables = detect_table_placeholders(text)
            try:
                extracted_tables = page.extract_tables() or []
            except Exception:
                extracted_tables = []
            for table_index, table in enumerate(extracted_tables, start=1):
                tables.append(
                    {
                        "kind": "pdf_table",
                        "table_index": table_index,
                        "row_count": len(table),
                        "column_count": max((len(row or []) for row in table), default=0),
                        "extraction_method": "pdfplumber",
                    }
                )
            pages.append(ParsedPage(index, text, "pdfplumber", tables))
    return pages


def extract_text_from_html(path: Path) -> ParsedDocument:
    content = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(content, "html.parser")
    tables = detect_html_tables(soup)

    extracted = trafilatura.extract(content) or ""
    method = "trafilatura"
    if not extracted:
        extracted = soup.get_text(" ")
        method = "beautifulsoup"

    text = normalize_whitespace(extracted)
    pages = [ParsedPage(None, text, method, tables)] if text or tables else []
    return ParsedDocument(
        text=text,
        pages=pages,
        metadata={
            "parser": method,
            "html_table_count": len(tables),
            "title": extract_title_from_html(content.encode("utf-8")),
        },
    )


def extract_text_from_plain_file(path: Path) -> ParsedDocument:
    text = normalize_whitespace(path.read_text(encoding="utf-8", errors="ignore"))
    pages = [ParsedPage(None, text, "plain_text", detect_table_placeholders(text))] if text else []
    return ParsedDocument(text=text, pages=pages, metadata={"parser": "plain_text"})


def parse_raw_file(
    path: Path,
    source_type: str,
    mime_type: str | None = None,
    ocr_engine: OCREngine | None = None,
) -> ParsedDocument:
    suffix = path.suffix.lower()
    if source_type == "pdf" or suffix == ".pdf" or mime_type == "application/pdf":
        return extract_text_from_pdf(path, ocr_engine=ocr_engine)
    if source_type == "html" or suffix in {".html", ".htm"} or (mime_type or "").startswith("text/html"):
        return extract_text_from_html(path)
    if suffix in {".txt", ".csv"} or (mime_type or "").startswith("text/"):
        return extract_text_from_plain_file(path)
    return ParsedDocument(text="", pages=[], metadata={"parser": "unsupported", "source_type": source_type})


def build_chunks(
    report_id: str,
    parsed: ParsedDocument | list[dict[str, Any]],
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[dict[str, Any]]:
    pages = _coerce_pages(parsed)
    parser_metadata = parsed.metadata if isinstance(parsed, ParsedDocument) else {"parser": "legacy_pages"}
    records: list[dict[str, Any]] = []

    for page in pages:
        for chunk_index, chunk in enumerate(chunk_text_by_tokens(page.text, target_tokens, min_tokens, max_tokens), start=1):
            records.append(
                {
                    "report_id": report_id,
                    "chunk_text": chunk,
                    "page_number": page.page_number,
                    "section_title": None,
                    "chunk_type": infer_chunk_type(chunk, page.tables),
                    "token_count": count_tokens_rough(chunk),
                    "metadata": {
                        "parser": parser_metadata.get("parser"),
                        "page_extraction_method": page.extraction_method,
                        "chunk_index_on_page": chunk_index,
                        "target_tokens": target_tokens,
                        "table_placeholders": page.tables,
                        **page.metadata,
                    },
                }
            )
    return records


def chunk_text_by_tokens(
    text: str,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []
    if len(words) <= max_tokens:
        return [" ".join(words)]

    chunks: list[str] = []
    start = 0
    overlap = max(80, target_tokens // 10)
    while start < len(words):
        end = min(start + target_tokens, len(words))
        if len(words) - end < min_tokens // 2:
            end = len(words)
        chunk_words = words[start:end]
        if len(chunk_words) > max_tokens:
            chunk_words = chunk_words[:max_tokens]
            end = start + max_tokens
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
        start = max(end - overlap, start + 1)
    return chunks


def parsed_json(parsed: ParsedDocument | str, pages: list[dict[str, Any]] | None = None) -> str:
    if isinstance(parsed, ParsedDocument):
        return parsed.to_json()
    legacy_pages = pages or []
    return json.dumps({"text_length": len(parsed), "pages": legacy_pages}, ensure_ascii=True, indent=2)


def pages_json(parsed: ParsedDocument) -> str:
    return json.dumps(
        [
            {
                "page_number": page.page_number,
                "text": page.text,
                "text_length": len(page.text),
                "extraction_method": page.extraction_method,
                "tables": page.tables,
                "metadata": page.metadata,
            }
            for page in parsed.pages
        ],
        ensure_ascii=True,
        indent=2,
    )


def infer_chunk_type(text: str, tables: list[dict[str, Any]] | None = None) -> str:
    if tables:
        return "table"
    lowered = text.lower()
    if "methodology" in lowered or "method" in lowered:
        return "methodology"
    if "source:" in lowered or "data source" in lowered:
        return "source_note"
    if "table " in lowered[:120]:
        return "table"
    if "footnote" in lowered:
        return "footnote"
    return "narrative"


def detect_html_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        rows = table.find_all("tr")
        columns = max((len(row.find_all(["td", "th"])) for row in rows), default=0)
        caption = table.find("caption")
        tables.append(
            {
                "kind": "html_table",
                "table_index": table_index,
                "row_count": len(rows),
                "column_count": columns,
                "caption": caption.get_text(" ", strip=True) if caption else None,
            }
        )
    return tables


def detect_table_placeholders(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    if "table " not in lowered and "\t" not in text:
        return []
    return [{"kind": "text_table_hint", "reason": "table_keyword_or_tabular_text"}]


def _join_page_text(pages: list[ParsedPage]) -> str:
    return "\n\n".join(page.text for page in pages if page.text)


def _coerce_pages(parsed: ParsedDocument | list[dict[str, Any]]) -> list[ParsedPage]:
    if isinstance(parsed, ParsedDocument):
        return parsed.pages
    return [
        ParsedPage(
            page_number=page.get("page_number"),
            text=page.get("text", ""),
            extraction_method=page.get("extraction_method", "legacy"),
            tables=page.get("tables", []),
            metadata=page.get("metadata", {}),
        )
        for page in parsed
    ]


def _quality_metadata(quality: ExtractionQuality) -> dict[str, Any]:
    return {
        "total_characters": quality.total_characters,
        "average_characters_per_page": quality.average_characters_per_page,
        "empty_page_ratio": quality.empty_page_ratio,
        "ocr_recommended": quality.ocr_recommended,
        "reason": quality.reason,
    }


def _parse_paddleocr_result(ocr_result: Any) -> tuple[str, float | None]:
    lines: list[str] = []
    confidences: list[float] = []
    pages = ocr_result or []
    if pages and isinstance(pages[0], list) and pages[0] and _looks_like_ocr_line(pages[0][0]):
        pages = [pages]

    for page in pages:
        for line in page or []:
            if not _looks_like_ocr_line(line):
                continue
            text_confidence = line[1]
            if not isinstance(text_confidence, (list, tuple)) or not text_confidence:
                continue
            text = str(text_confidence[0]).strip()
            if text:
                lines.append(text)
            if len(text_confidence) > 1 and isinstance(text_confidence[1], (int, float)):
                confidences.append(float(text_confidence[1]))

    confidence = sum(confidences) / len(confidences) if confidences else None
    return " ".join(lines), confidence


def _looks_like_ocr_line(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= 2
