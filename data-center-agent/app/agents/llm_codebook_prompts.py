import json
from typing import Any


EXTRACTION_SCHEMA = {
    "items": [
        {
            "item_type": "codebook_variable | chart_metric | policy_category | analytical_claim | data_source_reference | reject",
            "raw_variable_name": "string or null",
            "definition": "string or null",
            "measurement_method": "string or null",
            "unit": "string or null",
            "data_source_text": "string or null",
            "data_source_type": "public_dataset | private_database | survey | estimate | report_table | unknown",
            "availability": "obtainable | not_obtainable | private | unclear",
            "temporal_coverage": "string or null",
            "geographic_coverage": "string or null",
            "evidence_chunk_id": "uuid string or null",
            "evidence_quote": "short quote copied from chunk or null",
            "keep_for_codebook": True,
            "reason": "brief explanation",
            "confidence_score": 0.0,
        }
    ]
}

REVIEW_SCHEMA = {
    "reviewed_items": [
        {
            "original_index": 0,
            "review_decision": "valid_codebook_variable | chart_metric_only | policy_category | analytical_claim | source_reference | reject",
            "keep_for_codebook": True,
            "review_reason": "brief explanation",
            "confidence_adjustment": 0.0,
        }
    ]
}


def build_codebook_extraction_prompt(report_metadata: dict[str, Any], selected_chunks: list[Any]) -> str:
    chunks = [chunk.to_prompt_dict() if hasattr(chunk, "to_prompt_dict") else dict(chunk) for chunk in selected_chunks]
    return (
        "You are extracting a high-precision codebook from government, industry, policy, or research reports.\n\n"
        "Definition of a true codebook variable:\n"
        "A variable, indicator, or metric that has at least one explicit definition, measurement method, unit, formula, "
        "data source tied to the measure, or temporal/geographic coverage tied to the measure.\n\n"
        "Classify each possible item as one of: codebook_variable, chart_metric, policy_category, analytical_claim, "
        "data_source_reference, reject.\n\n"
        "Do NOT extract section headings, analytical claims, article titles, company/publication names, policy categories "
        "or technology families unless they are measured indicators, source citations, bibliography entries, chart notes "
        "alone, vague topics, narrative highlights, or general claims.\n\n"
        "Rules:\n"
        "1. Return valid JSON only.\n"
        "2. It is acceptable to return {\"items\": []}.\n"
        "3. Do not invent variables.\n"
        "4. Every kept codebook_variable must have evidence_chunk_id and evidence_quote.\n"
        "5. If evidence is weak or missing, classify as reject or chart_metric, not codebook_variable.\n"
        "6. If something is only a chart note without a definition, classify as chart_metric and keep_for_codebook=false.\n"
        "7. If something is a policy category, taxonomy, section heading, or analytical claim, reject.\n"
        "8. If source mentions PitchBook, Crunchbase, CB Insights, Preqin, Dealroom, Refinitiv, Bloomberg, Capital IQ, "
        "proprietary database, private database, subscription database, or paid database, classify underlying data as private_database/private.\n"
        "9. If source mentions official statistics, government statistics, statistical bureau, census, data.gov, World Bank, "
        "OECD, IMF, UN Data, or public open data portal, classify as public_dataset/obtainable when tied to a measure.\n"
        "10. Media citations or bibliography entries are not data sources unless the text explicitly says the data are from them.\n\n"
        f"Required JSON schema:\n{json.dumps(EXTRACTION_SCHEMA, ensure_ascii=True, indent=2)}\n\n"
        f"Report metadata:\n{json.dumps(report_metadata, ensure_ascii=True, default=str, indent=2)}\n\n"
        f"Selected chunks:\n{json.dumps(chunks, ensure_ascii=True, default=str, indent=2)}"
    )


def build_codebook_review_prompt(extracted_items: list[dict[str, Any]]) -> str:
    return (
        "You are reviewing candidate codebook variables for precision.\n"
        "Classify each candidate as valid_codebook_variable, chart_metric_only, policy_category, analytical_claim, "
        "source_reference, or reject. Only true measured variables with evidence should be kept.\n\n"
        f"Required JSON schema:\n{json.dumps(REVIEW_SCHEMA, ensure_ascii=True, indent=2)}\n\n"
        f"Candidates:\n{json.dumps(extracted_items, ensure_ascii=True, default=str, indent=2)}"
    )
