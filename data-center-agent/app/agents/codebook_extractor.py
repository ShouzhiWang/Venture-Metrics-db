import json
import re
from abc import ABC, abstractmethod
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.variable import CandidateChunk, ExtractionVerificationResult, ExtractedVariable


KEYWORDS = {
    "variable": 1.0,
    "variables": 1.0,
    "indicator": 1.0,
    "indicators": 1.0,
    "metric": 1.0,
    "measure": 0.9,
    "measured by": 1.7,
    "measured as": 1.7,
    "defined as": 1.8,
    "calculated as": 1.7,
    "methodology": 1.3,
    "methods": 1.1,
    "data source": 1.5,
    "data sources": 1.5,
    "source:": 1.3,
    "database": 0.8,
    "survey": 0.9,
    "sample": 0.6,
    "coverage": 0.8,
    "temporal coverage": 1.4,
    "geographic coverage": 1.4,
    "unit": 0.8,
    "definition": 1.1,
    "proxy for": 1.6,
    "index": 0.5,
    "score": 0.4,
    "table": 0.4,
    "appendix": 0.5,
    "notes": 0.5,
    "technical notes": 1.1,
}

SECTION_BOOSTS = {
    "methodology": 2.5,
    "methods": 2.0,
    "data and methods": 3.0,
    "data sources": 3.0,
    "indicator framework": 3.0,
    "indicators": 2.5,
    "variable definitions": 3.5,
    "definitions": 2.5,
    "appendix": 1.5,
    "technical notes": 2.5,
    "notes to tables": 2.0,
    "measurement": 2.5,
    "data coverage": 2.5,
}

CHUNK_TYPE_BOOSTS = {
    "methodology": 2.0,
    "source_note": 1.7,
    "table": 0.7,
    "footnote": 0.8,
}

PRIVATE_SOURCE_PATTERNS = [
    "pitchbook",
    "crunchbase",
    "cb insights",
    "preqin",
    "dealroom",
    "refinitiv",
    "bloomberg",
    "factset",
    "capital iq",
    "s&p capital iq",
    "proprietary database",
    "private database",
    "subscription database",
    "market research firm",
    "paid database",
]

PUBLIC_SOURCE_PATTERNS = [
    "official statistics",
    "government statistics",
    "statistical bureau",
    "census",
    "data.gov",
    "world bank",
    "oecd",
    "imf",
    "un data",
    "national bureau of statistics",
    "census and statistics department",
    "companies registry",
    "public dataset",
    "open data portal",
]

SURVEY_PATTERNS = ["survey", "questionnaire", "respondent", "sample", "interview"]
ESTIMATE_PATTERNS = ["estimated", "modeled", "modelled", "imputed", "forecast", "projection"]
VAGUE_NAMES = {"index", "score", "indicator", "metric", "measure", "variable"}
DIRECTIONAL_LABELS = {"up", "flat", "down", "increase", "decrease", "higher", "lower"}
CHART_LABEL_TERMS = {"source", "legend", "axis", "chart", "figure", "note", "notes"}
STRONG_DEFINITION_TERMS = ["defined as", "measured as", "measured by", "calculated as", "proxy for", "definition"]


class LLMVariableOutput(BaseModel):
    raw_variable_name: str
    definition: str | None = None
    measurement_method: str | None = None
    unit: str | None = None
    data_source_text: str | None = None
    data_source_type: str = "unknown"
    availability: str = "unclear"
    temporal_coverage: str | None = None
    geographic_coverage: str | None = None
    evidence_chunk_ids: list[UUID]
    evidence_quotes: list[str]
    confidence_score: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str] = Field(default_factory=list)


class LLMCodebookOutput(BaseModel):
    variables: list[LLMVariableOutput] = Field(default_factory=list)


class CandidateChunkSelector:
    def select(self, chunks: list[Any], top_k: int = 40) -> list[CandidateChunk]:
        candidates = [self._score_chunk(chunk) for chunk in chunks]
        candidates = [candidate for candidate in candidates if candidate.score > 0]
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:top_k]

    def _score_chunk(self, chunk: Any) -> CandidateChunk:
        chunk_id = _get(chunk, "id") or _get(chunk, "chunk_id")
        text = _get(chunk, "chunk_text") or ""
        section_title = _get(chunk, "section_title")
        chunk_type = _get(chunk, "chunk_type")
        lowered = text.lower()
        score = 0.0
        reasons: list[str] = []

        for keyword, weight in KEYWORDS.items():
            if keyword in lowered:
                occurrences = lowered.count(keyword)
                score += min(weight * occurrences, weight * 3)
                reasons.append(f"keyword:{keyword}")

        if section_title:
            title_lowered = str(section_title).lower()
            for section, boost in SECTION_BOOSTS.items():
                if section in title_lowered:
                    score += boost
                    reasons.append(f"section:{section}")

        if chunk_type:
            type_boost = CHUNK_TYPE_BOOSTS.get(str(chunk_type), 0.0)
            if type_boost:
                score += type_boost
                reasons.append(f"chunk_type:{chunk_type}")
            elif chunk_type == "unknown" and score >= 2.5:
                score += 0.5
                reasons.append("chunk_type:unknown_keyword_rich")

        if _looks_like_chart_legend_text(text) and not _has_strong_definition_language(text):
            penalty = min(score * 0.5, 3.0) or 1.0
            score -= penalty
            reasons.append(f"penalty:chart_legend_like:-{round(penalty, 3)}")

        return CandidateChunk(
            chunk_id=chunk_id,
            report_id=_get(chunk, "report_id"),
            chunk_text=text,
            page_number=_get(chunk, "page_number"),
            section_title=section_title,
            chunk_type=chunk_type,
            score=round(score, 3),
            reasons=reasons,
            metadata={"embedding_similarity_score": None},
        )


def classify_source_availability(text: str | None) -> tuple[str, str, dict[str, Any]]:
    lowered = (text or "").lower()
    matched = _first_match(lowered, PRIVATE_SOURCE_PATTERNS)
    if matched:
        return "private_database", "private", {"matched_pattern": matched}

    public_match = _first_match(lowered, PUBLIC_SOURCE_PATTERNS)
    survey_match = _first_match(lowered, SURVEY_PATTERNS)
    estimate_match = _first_match(lowered, ESTIMATE_PATTERNS)
    if public_match:
        return "public_dataset", "obtainable", {"matched_pattern": public_match}
    if survey_match:
        return "survey", "unclear", {"matched_pattern": survey_match}
    if estimate_match:
        return "estimate", "unclear", {"matched_pattern": estimate_match}
    return "unknown", "unclear", {"matched_pattern": None}


class CodebookExtractor(ABC):
    @abstractmethod
    def extract(self, report_id: UUID, chunks: list[Any]) -> list[ExtractedVariable]:
        raise NotImplementedError


class RuleBasedCodebookExtractor(CodebookExtractor):
    definition_patterns = [
        re.compile(
            r"(?P<name>[A-Z][A-Za-z0-9()/% ,_-]{2,80})\s+is\s+defined\s+as\s+(?P<value>[^.]{8,500})\.",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<name>[A-Z][A-Za-z0-9()/% ,_-]{2,80})\s+is\s+measured\s+(?:as|by)\s+(?P<value>[^.]{8,500})\.",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<name>[A-Z][A-Za-z0-9()/% ,_-]{2,80})\s+is\s+calculated\s+as\s+(?P<value>[^.]{8,500})\.",
            re.IGNORECASE,
        ),
        re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9()/% ,_-]{2,80})\s*:\s*(?P<value>[^.\n]{12,500})", re.IGNORECASE),
        re.compile(
            r"We\s+use\s+(?P<name>[A-Za-z][A-Za-z0-9()/% ,_-]{2,80})\s+as\s+a\s+proxy\s+for\s+(?P<value>[^.]{5,300})\.",
            re.IGNORECASE,
        ),
        re.compile(
            r"The\s+indicator\s+(?P<name>[A-Za-z][A-Za-z0-9()/% ,_-]{2,80})\s+(?P<value>[^.]{10,500})\.",
            re.IGNORECASE,
        ),
    ]

    def extract(self, report_id: UUID, chunks: list[Any]) -> list[ExtractedVariable]:
        extracted: list[ExtractedVariable] = []
        for chunk in chunks:
            chunk_id = _get(chunk, "chunk_id") or _get(chunk, "id")
            if not chunk_id:
                continue
            text = _get(chunk, "chunk_text") or ""
            for pattern in self.definition_patterns:
                for match in pattern.finditer(text):
                    variable = self._build_variable(report_id, chunk, match)
                    if variable:
                        extracted.append(variable)
        return extracted

    def _build_variable(self, report_id: UUID, chunk: Any, match: re.Match[str]) -> ExtractedVariable | None:
        raw_name = _clean_variable_name(match.group("name"))
        if _is_vague_variable_name(raw_name):
            return None
        value = _clean_sentence_fragment(match.group("value"))
        full_text = _get(chunk, "chunk_text") or ""
        sentence = _sentence_containing(full_text, match.group(0)) or match.group(0)
        data_source_text = _extract_data_source_text(full_text)
        source_type, availability, source_meta = classify_source_availability(data_source_text or full_text)
        temporal_coverage = _extract_temporal_coverage(full_text)
        geographic_coverage = _extract_geographic_coverage(full_text)
        pattern_text = match.re.pattern.lower()
        is_measurement = any(token in pattern_text for token in ["measured", "calculated", "proxy"])
        confidence = 0.66 if not is_measurement else 0.62
        if data_source_text:
            confidence += 0.05
        if temporal_coverage:
            confidence += 0.03

        return ExtractedVariable(
            report_id=report_id,
            raw_variable_name=raw_name,
            definition=value if not is_measurement else None,
            measurement_method=value if is_measurement else None,
            unit=_extract_unit(full_text),
            data_source_text=data_source_text,
            data_source_type=source_type,
            availability=availability,
            temporal_coverage=temporal_coverage,
            geographic_coverage=geographic_coverage,
            page_number=_get(chunk, "page_number"),
            evidence_chunk_id=_get(chunk, "chunk_id") or _get(chunk, "id"),
            evidence_quote=sentence[:500],
            confidence_score=min(confidence, 0.85),
            review_status="pending",
            metadata={"extractor": "rule_based", "source_classifier": source_meta, "pattern": match.re.pattern},
        )


class LLMCodebookExtractor(CodebookExtractor):
    def build_prompt(self, chunks: list[CandidateChunk]) -> str:
        return build_llm_codebook_prompt(chunks)

    def extract(self, report_id: UUID, chunks: list[Any]) -> list[ExtractedVariable]:
        raise NotImplementedError("LLM provider integration is not implemented yet.")


class MockLLMCodebookExtractor(LLMCodebookExtractor):
    def __init__(self, output: LLMCodebookOutput | dict[str, Any] | None = None):
        self.output = LLMCodebookOutput.model_validate(output or {"variables": []})

    def extract(self, report_id: UUID, chunks: list[Any]) -> list[ExtractedVariable]:
        chunk_lookup = {_get(chunk, "chunk_id") or _get(chunk, "id"): chunk for chunk in chunks}
        variables: list[ExtractedVariable] = []
        for item in self.output.variables:
            if not item.evidence_chunk_ids:
                continue
            evidence_chunk_id = item.evidence_chunk_ids[0]
            chunk = chunk_lookup.get(evidence_chunk_id)
            variables.append(
                ExtractedVariable(
                    report_id=report_id,
                    raw_variable_name=item.raw_variable_name,
                    definition=item.definition,
                    measurement_method=item.measurement_method,
                    unit=item.unit,
                    data_source_text=item.data_source_text,
                    data_source_type=item.data_source_type,
                    availability=item.availability,
                    temporal_coverage=item.temporal_coverage,
                    geographic_coverage=item.geographic_coverage,
                    page_number=_get(chunk, "page_number") if chunk else None,
                    evidence_chunk_id=evidence_chunk_id,
                    evidence_quote=item.evidence_quotes[0] if item.evidence_quotes else None,
                    confidence_score=item.confidence_score,
                    review_status="pending",
                    metadata={"extractor": "mock_llm", "uncertainties": item.uncertainties},
                )
            )
        return variables


def build_llm_codebook_prompt(chunks: list[CandidateChunk]) -> str:
    chunk_payload = [
        {
            "chunk_id": str(chunk.chunk_id),
            "page_number": chunk.page_number,
            "section_title": chunk.section_title,
            "chunk_type": chunk.chunk_type,
            "text": chunk.chunk_text,
        }
        for chunk in chunks
    ]
    return (
        "You are extracting a variable codebook from government, policy, industry, or research reports.\n\n"
        "You will receive selected report chunks. Each chunk has:\n"
        "- chunk_id\n- page_number\n- section_title\n- chunk_type\n- text\n\n"
        "Task:\nExtract variables, indicators, metrics, or measures that the report uses.\n\n"
        "For each variable, return:\n"
        "- raw_variable_name\n- definition\n- measurement_method\n- unit\n- data_source_text\n"
        "- data_source_type\n- availability\n- temporal_coverage\n- geographic_coverage\n"
        "- evidence_chunk_ids\n- evidence_quotes\n- confidence_score\n- uncertainties\n\n"
        "Rules:\n"
        "1. Only extract variables supported by the provided chunks.\n"
        "2. Do not invent variables.\n"
        "3. If a field is not stated, use null.\n"
        "4. Every variable must include at least one evidence_chunk_id.\n"
        "5. Every variable must include a short evidence quote copied from the chunk.\n"
        "6. Classify private/proprietary data sources carefully.\n"
        "7. If the report references PitchBook, Crunchbase, CB Insights, Preqin, Dealroom, Refinitiv, Bloomberg, proprietary database, or subscription database, classify as private_database and availability private.\n"
        "8. If the report references official statistics, census, data.gov, World Bank, OECD, government statistics, statistical bureau, or public open data portals, classify as public_dataset and availability obtainable.\n"
        "9. If source availability is unclear, use availability unclear.\n"
        "10. Return valid JSON only.\n\n"
        f"Selected chunks:\n{json.dumps(chunk_payload, ensure_ascii=True, indent=2)}"
    )


class EvidenceVerifier:
    def verify(self, variable: ExtractedVariable, chunks: list[Any]) -> ExtractionVerificationResult:
        warnings: list[str] = []
        chunk_lookup = {_get(chunk, "chunk_id") or _get(chunk, "id"): chunk for chunk in chunks}
        chunk = chunk_lookup.get(variable.evidence_chunk_id)
        if not variable.evidence_chunk_id or not chunk:
            return ExtractionVerificationResult(
                is_supported=False,
                evidence_quote_found=False,
                source_supported=False,
                temporal_supported=False,
                geographic_supported=False,
                warnings=["missing_or_unknown_evidence_chunk_id"],
                confidence_adjustment=-0.35,
                metadata={},
            )

        text = _get(chunk, "chunk_text") or ""
        quote_found = _quote_supported(variable.evidence_quote, text)
        if not quote_found:
            warnings.append("evidence_quote_not_found")

        source_supported = _field_supported(variable.data_source_text, text)
        temporal_supported = _field_supported(variable.temporal_coverage, text)
        geographic_supported = _field_supported(variable.geographic_coverage, text)
        name_supported = _field_supported(variable.raw_variable_name, text)

        if variable.data_source_text and not source_supported:
            warnings.append("data_source_text_not_supported")
        if variable.temporal_coverage and not temporal_supported:
            warnings.append("temporal_coverage_not_supported")
        if variable.geographic_coverage and not geographic_supported:
            warnings.append("geographic_coverage_not_supported")
        if not name_supported:
            warnings.append("variable_name_not_found_in_evidence")

        adjustment = 0.0
        if quote_found:
            adjustment += 0.05
        else:
            adjustment -= 0.15
        if variable.data_source_text and not source_supported:
            adjustment -= 0.06
        if variable.temporal_coverage and not temporal_supported:
            adjustment -= 0.04
        if variable.geographic_coverage and not geographic_supported:
            adjustment -= 0.04
        if not name_supported:
            adjustment -= 0.08

        is_supported = quote_found and name_supported and not (variable.data_source_text and not source_supported)
        return ExtractionVerificationResult(
            is_supported=is_supported,
            evidence_quote_found=quote_found,
            source_supported=source_supported,
            temporal_supported=temporal_supported,
            geographic_supported=geographic_supported,
            warnings=warnings,
            confidence_adjustment=adjustment,
            metadata={"evidence_chunk_id": str(variable.evidence_chunk_id)},
        )


class ConfidenceScorer:
    def score(
        self,
        variable: ExtractedVariable,
        verification: ExtractionVerificationResult,
        evidence_chunk: Any | None = None,
    ) -> ExtractedVariable:
        score = _clamp(variable.confidence_score)
        if variable.definition:
            score += 0.10
        if variable.measurement_method:
            score += 0.10
        if variable.data_source_text:
            score += 0.08
        if variable.temporal_coverage:
            score += 0.05
        if variable.geographic_coverage:
            score += 0.05
        if verification.evidence_quote_found:
            score += 0.10

        chunk_type = _get(evidence_chunk, "chunk_type") if evidence_chunk else None
        if chunk_type in {"methodology", "source_note", "table"}:
            score += 0.05
        if chunk_type in {"table", "figure", "chart"}:
            score -= 0.08

        if not verification.metadata.get("evidence_chunk_id"):
            score -= 0.25
        if not verification.evidence_quote_found:
            score -= 0.15
        chunk_metadata = _get(evidence_chunk, "metadata") or {}
        if chunk_metadata.get("page_extraction_method") == "ocr" or chunk_metadata.get("is_scanned_pdf"):
            score -= 0.10
        if _is_vague_variable_name(variable.raw_variable_name):
            score -= 0.10
        if variable.availability in {"private", "unclear"} and not verification.is_supported:
            score -= 0.10
        score += verification.confidence_adjustment
        score = _clamp(score)

        if score >= 0.80:
            status = "pending_high_confidence"
        elif score >= 0.55:
            status = "pending"
        else:
            status = "needs_review"

        metadata = {
            **variable.metadata,
            "verification": verification.model_dump(mode="json"),
            "confidence_inputs": {
                "chunk_type": chunk_type,
                "evidence_quote_found": verification.evidence_quote_found,
                "ocr_penalty_applied": bool(chunk_metadata.get("page_extraction_method") == "ocr" or chunk_metadata.get("is_scanned_pdf")),
            },
        }
        return variable.model_copy(update={"confidence_score": score, "review_status": status, "metadata": metadata})


class VariableQualityFilter:
    def filter(self, variable: ExtractedVariable, evidence_chunk: Any | None = None) -> ExtractedVariable | None:
        warnings = list(variable.metadata.get("quality_warnings", []))
        original_name = variable.raw_variable_name
        cleaned_name = clean_chart_label_variable_name(original_name)
        if cleaned_name != original_name:
            warnings.append(f"cleaned_chart_label_name:{original_name}")

        if _is_rejected_chart_label(cleaned_name):
            return None

        has_definition = bool(variable.definition)
        has_measurement = bool(variable.measurement_method)
        weak_evidence = not variable.evidence_quote or len(variable.evidence_quote.split()) < 5 or variable.confidence_score < 0.45
        if not has_definition and not has_measurement and weak_evidence:
            return None

        metadata = {**variable.metadata, "quality_warnings": warnings}
        status = variable.review_status
        confidence = variable.confidence_score
        chunk_type = _get(evidence_chunk, "chunk_type") if evidence_chunk else None
        text = _get(evidence_chunk, "chunk_text") or ""
        if chunk_type in {"table", "figure", "chart"} or (_looks_like_chart_legend_text(text) and not _has_strong_definition_language(text)):
            metadata["quality_warnings"].append("chart_or_table_derived_needs_review")
            status = "needs_review"
            confidence = min(confidence, 0.54)

        return variable.model_copy(
            update={
                "raw_variable_name": cleaned_name,
                "confidence_score": confidence,
                "review_status": status,
                "metadata": metadata,
            }
        )


class HybridCodebookExtractor(CodebookExtractor):
    def __init__(
        self,
        selector: CandidateChunkSelector | None = None,
        rule_extractor: RuleBasedCodebookExtractor | None = None,
        llm_extractor: LLMCodebookExtractor | None = None,
        verifier: EvidenceVerifier | None = None,
        scorer: ConfidenceScorer | None = None,
        quality_filter: VariableQualityFilter | None = None,
        top_k: int = 40,
    ):
        self.selector = selector or CandidateChunkSelector()
        self.rule_extractor = rule_extractor or RuleBasedCodebookExtractor()
        self.llm_extractor = llm_extractor
        self.verifier = verifier or EvidenceVerifier()
        self.scorer = scorer or ConfidenceScorer()
        self.quality_filter = quality_filter or VariableQualityFilter()
        self.top_k = top_k
        self.last_summary: dict[str, int] = {}

    def extract(self, report_id: UUID, chunks: list[Any]) -> list[ExtractedVariable]:
        candidate_chunks = self.selector.select(chunks, top_k=self.top_k)
        rule_variables = self.rule_extractor.extract(report_id, candidate_chunks)
        llm_variables = self.llm_extractor.extract(report_id, candidate_chunks) if self.llm_extractor else []
        merged = deduplicate_variables([*rule_variables, *llm_variables])
        chunk_lookup = {_get(chunk, "chunk_id") or _get(chunk, "id"): chunk for chunk in [*chunks, *candidate_chunks]}

        final: list[ExtractedVariable] = []
        filtered_count = 0
        downgraded_count = 0
        for variable in merged:
            evidence_chunk = chunk_lookup.get(variable.evidence_chunk_id)
            quality_checked = self.quality_filter.filter(variable, evidence_chunk)
            if not quality_checked:
                filtered_count += 1
                continue
            if quality_checked.review_status == "needs_review" and variable.review_status != "needs_review":
                downgraded_count += 1
            verification = self.verifier.verify(quality_checked, [*chunks, *candidate_chunks])
            scored = self.scorer.score(quality_checked, verification, evidence_chunk)
            if quality_checked.review_status == "needs_review":
                scored = scored.model_copy(
                    update={
                        "review_status": "needs_review",
                        "confidence_score": min(scored.confidence_score, quality_checked.confidence_score),
                        "metadata": {**scored.metadata, "quality_forced_needs_review": True},
                    }
                )
            if scored.evidence_chunk_id:
                final.append(scored)

        self.last_summary = {
            "candidate_chunks": len(candidate_chunks),
            "rule_based_variables": len(rule_variables),
            "llm_variables": len(llm_variables),
            "final_variables": len(final),
            "quality_filtered_variables": filtered_count,
            "quality_downgraded_variables": downgraded_count,
            "needs_review": sum(1 for variable in final if variable.review_status == "needs_review"),
            "private": sum(1 for variable in final if variable.availability == "private"),
        }
        return final


def deduplicate_variables(variables: list[ExtractedVariable]) -> list[ExtractedVariable]:
    grouped: dict[tuple[str, UUID], ExtractedVariable] = {}
    for variable in variables:
        key = (_normalize_name(variable.raw_variable_name), variable.evidence_chunk_id)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = variable
            continue
        grouped[key] = _prefer_variable(existing, variable)
    return list(grouped.values())


def extract_codebook_candidates(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not chunks:
        return []
    report_id = _get(chunks[0], "report_id")
    variables = HybridCodebookExtractor().extract(report_id, chunks)
    return [variable.model_dump(mode="json") for variable in variables]


def _prefer_variable(a: ExtractedVariable, b: ExtractedVariable) -> ExtractedVariable:
    def rank(variable: ExtractedVariable) -> tuple[int, int, float]:
        evidence_rank = 1 if variable.evidence_quote else 0
        completeness = sum(
            bool(value)
            for value in [
                variable.definition,
                variable.measurement_method,
                variable.unit,
                variable.data_source_text,
                variable.temporal_coverage,
                variable.geographic_coverage,
            ]
        )
        return evidence_rank, completeness, variable.confidence_score

    chosen, other = (b, a) if rank(b) > rank(a) else (a, b)
    duplicate_notes = chosen.metadata.get("duplicate_notes", [])
    duplicate_notes.append(
        {
            "raw_variable_name": other.raw_variable_name,
            "extractor": other.metadata.get("extractor"),
            "confidence_score": other.confidence_score,
        }
    )
    return chosen.model_copy(update={"metadata": {**chosen.metadata, "duplicate_notes": duplicate_notes}})


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if pattern in text:
            return pattern
    return None


def _clean_variable_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" :-,")
    name = re.sub(r"^(the|an|a)\s+", "", name, flags=re.IGNORECASE)
    return name[:100]


def clean_chart_label_variable_name(name: str) -> str:
    cleaned = re.sub(r"^[A-Z]\)\s*", "", name.strip())
    cleaned = re.sub(r"\bSource\b\s*:?.*$", "", cleaned, flags=re.IGNORECASE).strip(" :-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _clean_sentence_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ;:")


def _is_vague_variable_name(name: str) -> bool:
    normalized = _normalize_name(name).replace("_", " ")
    return normalized in VAGUE_NAMES or len(normalized) < 3


def _is_rejected_chart_label(name: str) -> bool:
    normalized = _normalize_name(name).replace("_", " ")
    tokens = set(normalized.split())
    if not normalized:
        return True
    if tokens and tokens <= (DIRECTIONAL_LABELS | CHART_LABEL_TERMS):
        return True
    if normalized in {"up flat down", "up flat down source", "source", "chart source"}:
        return True
    if _is_vague_variable_name(name):
        return True
    return False


def _looks_like_chart_legend_text(text: str) -> bool:
    lowered = text.lower()
    short = len(text.split()) <= 80
    directional_hits = sum(1 for token in DIRECTIONAL_LABELS if re.search(rf"\b{re.escape(token)}\b", lowered))
    chart_hits = sum(1 for token in ["source", "legend", "axis", "figure", "chart"] if token in lowered)
    return short and directional_hits >= 2 or (short and chart_hits >= 2)


def _has_strong_definition_language(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in STRONG_DEFINITION_TERMS)


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _sentence_containing(text: str, excerpt: str) -> str | None:
    normalized_excerpt = _clean_sentence_fragment(excerpt)
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if normalized_excerpt.lower() in sentence.lower():
            return sentence.strip()
    return None


def _extract_data_source_text(text: str) -> str | None:
    patterns = [
        r"Data\s+are\s+sourced\s+from\s+(?P<source>[^.]{3,180})\.",
        r"Data\s+is\s+sourced\s+from\s+(?P<source>[^.]{3,180})\.",
        r"Data\s+source(?:s)?\s*[:\-]\s*(?P<source>[^.]{3,180})\.",
        r"Source\s*[:\-]\s*(?P<source>[^.]{3,180})\.",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _clean_sentence_fragment(match.group("source"))
    source_type, _, metadata = classify_source_availability(text)
    matched = metadata.get("matched_pattern")
    return matched if source_type != "unknown" and matched else None


def _extract_temporal_coverage(text: str) -> str | None:
    match = re.search(r"(?:19|20)\d{2}\s*(?:[-–—]|to|through)\s*(?:19|20)\d{2}", text)
    if match:
        return match.group(0)
    match = re.search(r"cover(?:s|ing|ed)?\s+(?P<years>(?:19|20)\d{2}\s*(?:[-–—]|to|through)\s*(?:19|20)\d{2})", text, re.IGNORECASE)
    return match.group("years") if match else None


def _extract_geographic_coverage(text: str) -> str | None:
    match = re.search(r"geographic(?:al)? coverage\s*[:\-]\s*([^.;]{3,120})", text, re.IGNORECASE)
    if match:
        return _clean_sentence_fragment(match.group(1))
    match = re.search(r"cover(?:s|ing|ed)?\s+(?P<geo>national|provincial|city|county|regional|global|worldwide)\b", text, re.IGNORECASE)
    return match.group("geo") if match else None


def _extract_unit(text: str) -> str | None:
    match = re.search(r"unit(?:s)?\s*[:\-]\s*([^.;]{1,50})", text, re.IGNORECASE)
    if match:
        return _clean_sentence_fragment(match.group(1))
    match = re.search(r"\b(per\s+[\d,]+\s+[A-Za-z -]+)", text, re.IGNORECASE)
    return match.group(1) if match else None


def _quote_supported(quote: str | None, text: str) -> bool:
    if not quote:
        return False
    normalized_quote = _normalize_text(quote)
    normalized_text = _normalize_text(text)
    if normalized_quote in normalized_text:
        return True
    return _token_overlap(normalized_quote, normalized_text) >= 0.72 or SequenceMatcher(None, normalized_quote, normalized_text).ratio() >= 0.62


def _field_supported(value: str | None, text: str) -> bool:
    if not value:
        return True
    normalized_value = _normalize_text(value)
    normalized_text = _normalize_text(text)
    if normalized_value in normalized_text:
        return True
    return _token_overlap(normalized_value, normalized_text) >= 0.70


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _token_overlap(a: str, b: str) -> float:
    a_tokens = set(re.findall(r"[a-z0-9]+", a.lower()))
    b_tokens = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not a_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))
