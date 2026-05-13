from uuid import uuid4

from app.agents.codebook_extractor import (
    CandidateChunkSelector,
    ConfidenceScorer,
    EvidenceVerifier,
    HybridCodebookExtractor,
    LLMCodebookOutput,
    MockLLMCodebookExtractor,
    RuleBasedCodebookExtractor,
    VariableQualityFilter,
    classify_source_availability,
)
from app.agents.content_quality import classify_content_quality
from app.models.variable import ExtractedVariable


def chunk(text: str, *, chunk_type: str = "narrative", section_title: str | None = None, metadata: dict | None = None):
    return {
        "id": uuid4(),
        "report_id": uuid4(),
        "chunk_text": text,
        "page_number": 4,
        "section_title": section_title,
        "chunk_type": chunk_type,
        "metadata": metadata or {},
    }


def test_candidate_chunk_selector_ranks_methodology_source_chunks_higher() -> None:
    report_id = uuid4()
    relevant = {
        "id": uuid4(),
        "report_id": report_id,
        "chunk_text": "Methodology: Startup density is defined as startups per 1,000 residents. Data source: official statistics.",
        "page_number": 10,
        "section_title": "Data and Methods",
        "chunk_type": "methodology",
        "metadata": {},
    }
    irrelevant = {
        "id": uuid4(),
        "report_id": report_id,
        "chunk_text": "The city has a long history of entrepreneurship and regional growth.",
        "page_number": 1,
        "section_title": "Introduction",
        "chunk_type": "narrative",
        "metadata": {},
    }

    selected = CandidateChunkSelector().select([irrelevant, relevant], top_k=2)

    assert selected[0].chunk_id == relevant["id"]
    assert any(reason.startswith("keyword:defined as") for reason in selected[0].reasons)
    assert "section:data and methods" in selected[0].reasons


def test_candidate_chunk_selector_penalizes_chart_legend_chunks() -> None:
    report_id = uuid4()
    chart = {
        "id": uuid4(),
        "report_id": report_id,
        "chunk_text": "Up Flat Down Source: PitchBook Figure legend axis chart",
        "page_number": 4,
        "section_title": "Chart",
        "chunk_type": "table",
        "metadata": {},
    }
    methodology = {
        "id": uuid4(),
        "report_id": report_id,
        "chunk_text": "Methodology: Deal count is defined as the number of completed venture capital deals.",
        "page_number": 8,
        "section_title": "Methodology",
        "chunk_type": "methodology",
        "metadata": {},
    }

    selected = CandidateChunkSelector().select([chart, methodology], top_k=2)

    assert selected[0].chunk_id == methodology["id"]
    assert any(reason.startswith("penalty:chart_legend_like") for reason in selected[1].reasons)


def test_html_one_chunk_classified_low_text_or_landing_page_only() -> None:
    quality = classify_content_quality(
        [
            {
                "chunk_text": "Home About Contact Login Member News Copyright",
                "chunk_type": "narrative",
                "metadata": {},
            }
        ],
        source_type="html",
    )

    assert quality.label in {"low_text", "landing_page_only"}


def test_source_availability_classifier_private_public_survey() -> None:
    assert classify_source_availability("Data are sourced from PitchBook.")[:2] == ("private_database", "private")
    assert classify_source_availability("Crunchbase was used for company records.")[:2] == ("private_database", "private")
    assert classify_source_availability("Data use official statistics from the statistical bureau.")[:2] == (
        "public_dataset",
        "obtainable",
    )
    assert classify_source_availability("World Bank indicators are used.")[:2] == ("public_dataset", "obtainable")
    assert classify_source_availability("The indicator is based on a respondent survey sample.")[:2] == ("survey", "unclear")


def test_rule_based_extractor_extracts_startup_density_public_source() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    chunks = [
        {
            "id": chunk_id,
            "report_id": report_id,
            "chunk_text": "Startup density is defined as the number of startups per 1,000 working-age residents. Data are sourced from official government statistics and cover 2018–2023.",
            "page_number": 7,
            "section_title": "Indicator Framework",
            "chunk_type": "methodology",
            "metadata": {},
        }
    ]

    variables = RuleBasedCodebookExtractor().extract(report_id, chunks)

    assert len(variables) == 1
    variable = variables[0]
    assert variable.raw_variable_name == "Startup density"
    assert "number of startups" in variable.definition
    assert variable.data_source_type == "public_dataset"
    assert variable.availability == "obtainable"
    assert variable.temporal_coverage == "2018–2023"
    assert variable.evidence_chunk_id == chunk_id
    assert variable.evidence_quote
    assert variable.confidence_score > 0


def test_rule_based_extractor_extracts_vc_investment_private_source() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    chunks = [
        {
            "id": chunk_id,
            "report_id": report_id,
            "chunk_text": "Venture capital investment is measured as the total annual amount of VC funding received by startups. Data are sourced from PitchBook.",
            "page_number": 8,
            "section_title": "Definitions",
            "chunk_type": "methodology",
            "metadata": {},
        }
    ]

    variable = RuleBasedCodebookExtractor().extract(report_id, chunks)[0]

    assert variable.raw_variable_name == "Venture capital investment"
    assert "total annual amount" in variable.measurement_method
    assert variable.data_source_text == "PitchBook"
    assert variable.data_source_type == "private_database"
    assert variable.availability == "private"


def test_pitchbook_data_remains_private_after_quality_filter() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    text = "Venture capital investment is measured as the total annual amount of VC funding received by startups. Data are sourced from PitchBook."
    variable = RuleBasedCodebookExtractor().extract(
        report_id,
        [{"id": chunk_id, "report_id": report_id, "chunk_text": text, "chunk_type": "methodology", "metadata": {}}],
    )[0]

    filtered = VariableQualityFilter().filter(variable, {"id": chunk_id, "chunk_text": text, "chunk_type": "methodology", "metadata": {}})

    assert filtered is not None
    assert filtered.data_source_type == "private_database"
    assert filtered.availability == "private"


def test_rule_based_extractor_extracts_proxy_with_lower_confidence() -> None:
    report_id = uuid4()
    chunks = [
        {
            "id": uuid4(),
            "report_id": report_id,
            "chunk_text": "We use patent applications as a proxy for innovation output.",
            "page_number": 5,
            "section_title": "Methods",
            "chunk_type": "methodology",
            "metadata": {},
        }
    ]

    variable = RuleBasedCodebookExtractor().extract(report_id, chunks)[0]

    assert variable.raw_variable_name == "patent applications"
    assert "innovation output" in variable.measurement_method
    assert variable.review_status == "pending"
    assert variable.confidence_score < 0.75


def test_variable_quality_filter_cleans_chart_label_source_suffix() -> None:
    variable = ExtractedVariable(
        report_id=uuid4(),
        raw_variable_name="B) Deal count Source",
        definition="number of completed venture capital deals",
        evidence_chunk_id=uuid4(),
        evidence_quote="B) Deal count Source: number of completed venture capital deals.",
        confidence_score=0.62,
    )

    filtered = VariableQualityFilter().filter(variable, {"chunk_type": "table", "chunk_text": variable.evidence_quote, "metadata": {}})

    assert filtered is not None
    assert filtered.raw_variable_name == "Deal count"
    assert filtered.review_status == "needs_review"
    assert "cleaned_chart_label_name:B) Deal count Source" in filtered.metadata["quality_warnings"]


def test_variable_quality_filter_rejects_directional_legend_label() -> None:
    variable = ExtractedVariable(
        report_id=uuid4(),
        raw_variable_name="Up Flat Down Source",
        evidence_chunk_id=uuid4(),
        evidence_quote="Up Flat Down Source: PitchBook.",
        confidence_score=0.4,
    )

    assert VariableQualityFilter().filter(variable, {"chunk_type": "table", "chunk_text": variable.evidence_quote, "metadata": {}}) is None


def test_methodology_definition_survives_quality_filter() -> None:
    variable = ExtractedVariable(
        report_id=uuid4(),
        raw_variable_name="Startup density",
        definition="startups per 1,000 residents",
        evidence_chunk_id=uuid4(),
        evidence_quote="Startup density is defined as startups per 1,000 residents.",
        confidence_score=0.7,
    )

    filtered = VariableQualityFilter().filter(
        variable,
        {"chunk_type": "methodology", "chunk_text": variable.evidence_quote, "metadata": {}},
    )

    assert filtered is not None
    assert filtered.raw_variable_name == "Startup density"
    assert filtered.review_status == "pending"


def test_evidence_verifier_passes_when_quote_appears() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    text = "Startup density is defined as startups per 1,000 residents. Data are sourced from official statistics."
    variable = ExtractedVariable(
        report_id=report_id,
        raw_variable_name="Startup density",
        definition="startups per 1,000 residents",
        data_source_text="official statistics",
        evidence_chunk_id=chunk_id,
        evidence_quote="Startup density is defined as startups per 1,000 residents.",
        confidence_score=0.7,
    )

    result = EvidenceVerifier().verify(variable, [{"id": chunk_id, "report_id": report_id, "chunk_text": text}])

    assert result.is_supported is True
    assert result.evidence_quote_found is True
    assert result.source_supported is True


def test_evidence_verifier_warns_when_quote_or_source_missing() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    variable = ExtractedVariable(
        report_id=report_id,
        raw_variable_name="Startup density",
        definition="startups per 1,000 residents",
        data_source_text="PitchBook",
        evidence_chunk_id=chunk_id,
        evidence_quote="This quote is absent.",
        confidence_score=0.7,
    )

    result = EvidenceVerifier().verify(variable, [{"id": chunk_id, "report_id": report_id, "chunk_text": "Startup density is defined as startups per 1,000 residents."}])

    assert result.is_supported is False
    assert "evidence_quote_not_found" in result.warnings
    assert "data_source_text_not_supported" in result.warnings
    assert result.confidence_adjustment < 0


def test_confidence_scorer_thresholds_and_penalties() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    complete = ExtractedVariable(
        report_id=report_id,
        raw_variable_name="Startup density",
        definition="startups per 1,000 residents",
        measurement_method="count startups divided by residents",
        data_source_text="official statistics",
        temporal_coverage="2018-2023",
        geographic_coverage="national",
        evidence_chunk_id=chunk_id,
        evidence_quote="Startup density is defined as startups per 1,000 residents.",
        confidence_score=0.65,
    )
    verification = EvidenceVerifier().verify(
        complete,
        [
            {
                "id": chunk_id,
                "chunk_text": "Startup density is defined as startups per 1,000 residents. Data source: official statistics. Coverage is national and 2018-2023.",
                "chunk_type": "methodology",
                "metadata": {},
            }
        ],
    )

    scored = ConfidenceScorer().score(complete, verification, {"chunk_type": "methodology", "metadata": {}})

    assert scored.confidence_score >= 0.8
    assert scored.review_status == "pending_high_confidence"

    vague = complete.model_copy(update={"raw_variable_name": "score", "confidence_score": 0.56})
    low = ConfidenceScorer().score(
        vague,
        verification.model_copy(update={"evidence_quote_found": False, "is_supported": False, "confidence_adjustment": -0.15}),
        {"chunk_type": "narrative", "metadata": {"page_extraction_method": "ocr"}},
    )

    assert low.confidence_score < scored.confidence_score
    assert low.review_status in {"pending", "needs_review"}


def test_hybrid_extractor_combines_mock_llm_and_deduplicates() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    chunks = [
        {
            "id": chunk_id,
            "report_id": report_id,
            "chunk_text": "Startup density is defined as startups per 1,000 residents. Data are sourced from official statistics.",
            "page_number": 2,
            "section_title": "Variable Definitions",
            "chunk_type": "methodology",
            "metadata": {},
        }
    ]
    llm_output = LLMCodebookOutput(
        variables=[
            {
                "raw_variable_name": "Startup density",
                "definition": "startups per 1,000 residents",
                "measurement_method": None,
                "unit": "per 1,000 residents",
                "data_source_text": "official statistics",
                "data_source_type": "public_dataset",
                "availability": "obtainable",
                "temporal_coverage": None,
                "geographic_coverage": None,
                "evidence_chunk_ids": [chunk_id],
                "evidence_quotes": ["Startup density is defined as startups per 1,000 residents."],
                "confidence_score": 0.8,
                "uncertainties": [],
            }
        ]
    )

    extractor = HybridCodebookExtractor(llm_extractor=MockLLMCodebookExtractor(llm_output), top_k=5)
    variables = extractor.extract(report_id, chunks)

    assert len(variables) == 1
    assert variables[0].evidence_chunk_id == chunk_id
    assert variables[0].confidence_score > 0
    assert variables[0].review_status in {"pending_high_confidence", "pending", "needs_review"}
    assert extractor.last_summary["candidate_chunks"] == 1
    assert extractor.last_summary["rule_based_variables"] == 1
    assert extractor.last_summary["llm_variables"] == 1
