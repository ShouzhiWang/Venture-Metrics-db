import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.llm_candidate_selector import LLMCandidateChunkSelector
from app.agents.llm_codebook_parser import LLMParseError, parse_extraction_response
from app.agents.llm_codebook_prompts import build_codebook_extraction_prompt
from app.agents.llm_evidence import verify_llm_item
from app.llm.openai_batch_client import create_jsonl_file, make_response_request
from app.models.llm_codebook import LLMExtractedItem
from app.workers import import_extraction_batch as import_worker


def test_llm_candidate_selector_selects_methodology_and_excludes_references() -> None:
    report_id = uuid4()
    good = {
        "id": uuid4(),
        "report_id": report_id,
        "chunk_text": "Startup density is defined as the number of startups per 1,000 residents.",
        "section_title": "Methodology",
        "chunk_type": "methodology",
    }
    bad = {
        "id": uuid4(),
        "report_id": report_id,
        "chunk_text": "References BBC. Available from https://www.bbc.com.",
        "section_title": "References",
        "chunk_type": "narrative",
    }

    selected = LLMCandidateChunkSelector(max_chunks=5).select([bad, good])

    assert [chunk.chunk_id for chunk in selected] == [str(good["id"])]


def test_build_codebook_extraction_prompt_includes_schema_and_chunks() -> None:
    chunk = LLMCandidateChunkSelector().select(
        [
            {
                "id": uuid4(),
                "report_id": uuid4(),
                "chunk_text": "R&D intensity is defined as R&D expenditure as a percentage of GDP.",
                "section_title": "Definitions",
                "chunk_type": "methodology",
            }
        ]
    )[0]

    prompt = build_codebook_extraction_prompt({"title": "Report"}, [chunk])

    assert "codebook_variable" in prompt
    assert "evidence_chunk_id" in prompt
    assert chunk.chunk_id in prompt


def test_jsonl_generation_produces_unique_custom_ids(tmp_path: Path) -> None:
    requests = [
        make_response_request(custom_id="report:1:extract:v1", model="gpt-4.1-mini", prompt="{}", report_id="1", prompt_version="v1"),
        make_response_request(custom_id="report:2:extract:v1", model="gpt-4.1-mini", prompt="{}", report_id="2", prompt_version="v1"),
    ]

    path = create_jsonl_file(requests, tmp_path / "batch.jsonl")
    lines = [json.loads(line) for line in path.read_text().splitlines()]

    assert len(lines) == 2
    assert {line["custom_id"] for line in lines} == {"report:1:extract:v1", "report:2:extract:v1"}


def test_jsonl_generation_rejects_duplicate_custom_ids(tmp_path: Path) -> None:
    request = make_response_request(custom_id="duplicate", model="gpt-4.1-mini", prompt="{}")

    with pytest.raises(ValueError):
        create_jsonl_file([request, request], tmp_path / "batch.jsonl")


def test_parser_handles_valid_extraction_json() -> None:
    items = parse_extraction_response(
        {
            "output_text": json.dumps(
                {
                    "items": [
                        {
                            "item_type": "codebook_variable",
                            "raw_variable_name": "Startup density",
                            "evidence_chunk_id": str(uuid4()),
                            "evidence_quote": "Startup density is defined as the number of startups.",
                            "keep_for_codebook": True,
                            "confidence_score": 0.9,
                        }
                    ]
                }
            )
        }
    )

    assert items[0].raw_variable_name == "Startup density"


def test_parser_handles_json_inside_code_fences() -> None:
    items = parse_extraction_response('```json\n{"items": []}\n```')

    assert items == []


def test_parser_handles_invalid_json_gracefully() -> None:
    with pytest.raises(LLMParseError):
        parse_extraction_response("not json")


def test_evidence_verifier_rejects_missing_evidence_chunk_id() -> None:
    item = LLMExtractedItem(item_type="codebook_variable", raw_variable_name="Startup density", keep_for_codebook=True)

    passed, reason, _ = verify_llm_item(item, {})

    assert passed is False
    assert reason == "missing_evidence_chunk_id"


def test_evidence_verifier_accepts_quote_found_in_chunk() -> None:
    chunk_id = str(uuid4())
    item = LLMExtractedItem(
        item_type="codebook_variable",
        raw_variable_name="Startup density",
        definition="the number of startups per 1,000 residents",
        evidence_chunk_id=chunk_id,
        evidence_quote="Startup density is defined as the number of startups per 1,000 residents.",
        keep_for_codebook=True,
        confidence_score=0.9,
    )

    passed, reason, score = verify_llm_item(
        item,
        {chunk_id: {"chunk_text": "Startup density is defined as the number of startups per 1,000 residents."}},
    )

    assert passed is True
    assert reason is None
    assert score == 0.9


def test_insertion_filter_rejects_non_codebook_and_missing_evidence() -> None:
    report_id = uuid4()
    chunk_id = uuid4()
    non_codebook = LLMExtractedItem(item_type="analytical_claim", keep_for_codebook=True, confidence_score=0.95)
    missing_evidence = LLMExtractedItem(item_type="codebook_variable", keep_for_codebook=True, confidence_score=0.95)

    assert verify_llm_item(non_codebook, {})[0] is False
    assert verify_llm_item(missing_evidence, {str(chunk_id): {"chunk_text": "x"}})[0] is False


class FakeEngine:
    def begin(self):
        return self

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeBatchRepository:
    batch_id = uuid4()
    output_path = None

    def __init__(self, _connection):
        pass

    def get_batch_by_id(self, batch_id):
        return {
            "id": self.batch_id,
            "model": "gpt-4.1-mini",
            "prompt_version": "codebook_extraction_v1",
            "output_path": str(self.output_path),
            "output_file_id": None,
        }

    def mark_imported(self, batch_id, **values):
        return None


class FakeBatchItemRepository:
    report_id = uuid4()

    def __init__(self, _connection):
        pass

    def get_items_by_batch(self, batch_id):
        return [{"request_custom_id": f"report:{self.report_id}:extract:codebook_extraction_v1", "report_id": self.report_id}]

    def update_item_result(self, *args, **kwargs):
        return None


class FakeReportRepository:
    def __init__(self, _connection):
        pass

    def get(self, report_id):
        return {"id": report_id, "title": "Test report"}


class FakeChunkRepository:
    chunk_id = uuid4()

    def __init__(self, _connection):
        pass

    def list_by_report(self, report_id):
        return [
            {
                "id": self.chunk_id,
                "report_id": report_id,
                "chunk_text": "Startup density is defined as the number of startups per 1,000 residents.",
                "page_number": 3,
            }
        ]


class FakeVariableRepository:
    def __init__(self, _connection):
        pass

    def get_report_variables_by_report(self, report_id):
        return []

    def insert_many_report_variables(self, variables):
        return []


def test_import_logic_maps_custom_id_and_exports_csvs(tmp_path: Path, monkeypatch) -> None:
    custom_id = f"report:{FakeBatchItemRepository.report_id}:extract:codebook_extraction_v1"
    output_path = tmp_path / "output.jsonl"
    output_path.write_text(
        json.dumps(
            {
                "custom_id": custom_id,
                "response": {
                    "body": {
                        "output_text": json.dumps(
                            {
                                "items": [
                                    {
                                        "item_type": "codebook_variable",
                                        "raw_variable_name": "Startup density",
                                        "definition": "the number of startups per 1,000 residents",
                                        "evidence_chunk_id": str(FakeChunkRepository.chunk_id),
                                        "evidence_quote": "Startup density is defined as the number of startups per 1,000 residents.",
                                        "keep_for_codebook": True,
                                        "confidence_score": 0.9,
                                    }
                                ]
                            }
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    FakeBatchRepository.output_path = output_path
    monkeypatch.setattr(import_worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(import_worker, "BatchRepository", FakeBatchRepository)
    monkeypatch.setattr(import_worker, "BatchItemRepository", FakeBatchItemRepository)
    monkeypatch.setattr(import_worker, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(import_worker, "ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(import_worker, "VariableRepository", FakeVariableRepository)

    result = import_worker.import_extraction_batch(
        batch_id=str(FakeBatchRepository.batch_id),
        review_csv=tmp_path / "review.csv",
        output_dir=tmp_path,
        export_rejected=True,
    )

    assert result["accepted"] == 1
    assert result["rejected"] == 0
    assert "Startup density" in (tmp_path / "review.csv").read_text(encoding="utf-8")
