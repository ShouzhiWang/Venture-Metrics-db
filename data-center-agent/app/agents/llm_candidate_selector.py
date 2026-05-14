import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.codebook_extractor import is_reference_like_text


MEASUREMENT_KEYWORDS = {
    "defined as": 4.0,
    "measured as": 4.0,
    "measured by": 4.0,
    "calculated as": 4.0,
    "computed as": 4.0,
    "derived from": 3.0,
    "proxied by": 3.0,
    "based on data from": 3.0,
    "data are sourced from": 3.0,
    "indicator": 1.2,
    "variable": 1.2,
    "metric": 1.2,
    "unit": 1.0,
    "percentage of": 2.0,
    "number of": 2.0,
    "rate of": 2.0,
    "share of": 2.0,
    "ratio of": 2.0,
    "index of": 2.0,
    "total amount of": 2.0,
    "count of": 2.0,
}

SECTION_BOOSTS = {
    "methodology": 5.0,
    "methods": 4.0,
    "definitions": 5.0,
    "definition": 4.0,
    "data sources": 5.0,
    "technical notes": 4.0,
    "appendix": 2.0,
    "notes to tables": 3.0,
    "notes to figures": 3.0,
    "measurement": 4.0,
    "indicator": 3.0,
}

CHUNK_TYPE_BOOSTS = {
    "methodology": 3.0,
    "source_note": 2.0,
    "footnote": 1.0,
    "table": 0.5,
}


@dataclass
class LLMSelectedChunk:
    chunk_id: str
    report_id: str
    text: str
    page_number: int | None = None
    section_title: str | None = None
    chunk_type: str | None = None
    selector_score: float = 0.0
    selector_reasons: list[str] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "report_id": self.report_id,
            "page_number": self.page_number,
            "section_title": self.section_title,
            "chunk_type": self.chunk_type,
            "selector_score": round(self.selector_score, 3),
            "selector_reasons": self.selector_reasons,
            "text": self.text,
        }


class LLMCandidateChunkSelector:
    def __init__(self, max_chunks: int = 30, max_input_tokens: int = 45000, include_neighbors: bool = True):
        self.max_chunks = max_chunks
        self.max_input_tokens = max_input_tokens
        self.include_neighbors = include_neighbors

    def select(self, chunks: list[Any]) -> list[LLMSelectedChunk]:
        scored = [(index, self._score_chunk(chunk)) for index, chunk in enumerate(chunks)]
        eligible = [(index, selected) for index, selected in scored if selected.selector_score > 0]
        chosen_indexes = {index for index, _ in sorted(eligible, key=lambda item: item[1].selector_score, reverse=True)[: self.max_chunks]}

        if self.include_neighbors:
            by_report = [self._get(chunk, "report_id") for chunk in chunks]
            for index, selected in eligible:
                if index not in chosen_indexes or selected.selector_score < 5:
                    continue
                for neighbor in (index - 1, index + 1):
                    if 0 <= neighbor < len(chunks) and by_report[neighbor] == by_report[index]:
                        neighbor_selected = scored[neighbor][1]
                        if neighbor_selected.selector_score >= 0 and not self._is_excluded(chunks[neighbor]):
                            chosen_indexes.add(neighbor)

        selected = [scored[index][1] for index in sorted(chosen_indexes)]
        selected = sorted(selected, key=lambda item: item.selector_score, reverse=True)
        return self._cap_by_tokens(selected)[: self.max_chunks]

    def _score_chunk(self, chunk: Any) -> LLMSelectedChunk:
        text = self._get(chunk, "chunk_text") or ""
        section_title = self._get(chunk, "section_title")
        chunk_type = self._get(chunk, "chunk_type")
        score = 0.0
        reasons: list[str] = []

        if self._is_excluded(chunk):
            return self._selected(chunk, score=-1.0, reasons=["excluded"])

        lowered = text.lower()
        title_lowered = str(section_title or "").lower()
        for section, boost in SECTION_BOOSTS.items():
            if section in title_lowered:
                score += boost
                reasons.append(f"section:{section}")

        type_boost = CHUNK_TYPE_BOOSTS.get(str(chunk_type or ""), 0.0)
        if type_boost:
            score += type_boost
            reasons.append(f"chunk_type:{chunk_type}")

        for keyword, weight in MEASUREMENT_KEYWORDS.items():
            count = lowered.count(keyword)
            if count:
                score += min(weight * count, weight * 3)
                reasons.append(f"keyword:{keyword}")

        if re.search(r"\bdata (?:are|is) (?:from|sourced from)\b|\busing data from\b|\bbased on data from\b", lowered):
            score += 3.0
            reasons.append("data_source_signal")
        if self._url_density(text) > 0.05:
            score -= 4.0
            reasons.append("penalty:url_density")
        if self._looks_like_news_or_marketing(text) and not self._has_strong_methodology_language(text):
            score -= 3.0
            reasons.append("penalty:news_marketing")
        if self._looks_like_footer_header(text):
            score -= 3.0
            reasons.append("penalty:footer_header")

        return self._selected(chunk, score=max(score, 0.0), reasons=reasons)

    def _selected(self, chunk: Any, *, score: float, reasons: list[str]) -> LLMSelectedChunk:
        return LLMSelectedChunk(
            chunk_id=str(self._get(chunk, "id") or self._get(chunk, "chunk_id")),
            report_id=str(self._get(chunk, "report_id")),
            text=self._get(chunk, "chunk_text") or "",
            page_number=self._get(chunk, "page_number"),
            section_title=self._get(chunk, "section_title"),
            chunk_type=self._get(chunk, "chunk_type"),
            selector_score=round(score, 3),
            selector_reasons=reasons,
        )

    def _is_excluded(self, chunk: Any) -> bool:
        text = self._get(chunk, "chunk_text") or ""
        section_title = str(self._get(chunk, "section_title") or "").lower()
        if any(term in section_title for term in ["references", "bibliography", "endnotes", "works cited", "further reading"]):
            return True
        if is_reference_like_text(text):
            return True
        if self._url_density(text) > 0.12:
            return True
        if self._looks_like_footer_header(text):
            return True
        return False

    def _cap_by_tokens(self, chunks: list[LLMSelectedChunk]) -> list[LLMSelectedChunk]:
        total = 0
        capped: list[LLMSelectedChunk] = []
        for chunk in chunks:
            tokens = estimate_tokens(chunk.text)
            if total + tokens > self.max_input_tokens:
                remaining = max(self.max_input_tokens - total, 0)
                if remaining < 200:
                    break
                words = chunk.text.split()
                truncated = " ".join(words[: remaining * 3 // 4])
                capped.append(LLMSelectedChunk(**{**chunk.__dict__, "text": truncated}))
                break
            capped.append(chunk)
            total += tokens
        return capped

    @staticmethod
    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    @staticmethod
    def _url_density(text: str) -> float:
        words = max(len(text.split()), 1)
        return len(re.findall(r"https?://|www\.", text, re.IGNORECASE)) / words

    @staticmethod
    def _looks_like_footer_header(text: str) -> bool:
        lowered = text.lower()
        return len(text.split()) < 40 and any(term in lowered for term in ["copyright", "all rights reserved", "cookie", "newsletter", "subscribe"])

    @staticmethod
    def _looks_like_news_or_marketing(text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in ["press release", "contact us", "sign up", "newsletter", "read more", "advertisement"])

    @staticmethod
    def _has_strong_methodology_language(text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in ["defined as", "measured as", "calculated as", "data are sourced from"])


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
