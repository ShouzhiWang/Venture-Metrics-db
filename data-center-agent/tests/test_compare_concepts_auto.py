import json

from app.services.compare_concepts_auto import compare_concepts_auto
from app.workers import compare_concepts_auto as worker


def variable(
    report_id,
    variable_id,
    title,
    *,
    score=0.5,
    evidence=True,
    availability="public",
    item_type="codebook_variable",
    confidence=0.9,
    geography="Singapore",
):
    return {
        "object_type": "variable",
        "object_id": variable_id,
        "variable_id": variable_id,
        "report_id": report_id,
        "title": title,
        "score": score,
        "availability": availability,
        "geography": geography,
        "evidence_quote": "Evidence quote" if evidence else None,
        "metadata": {
            "definition": f"Definition for {title}",
            "measurement_method": "Count from table",
            "item_type": item_type,
            "confidence_score": confidence,
            "evidence_chunk_id": "chunk-1" if evidence else None,
        },
    }


def report(report_id, title, score=0.3):
    return {"object_type": "report", "object_id": report_id, "title": title, "score": score}


def fake_find_data(query, **kwargs):
    return {"query": query, "relevant_reports": [], "suggested_clarifications": []}


def test_selects_top_reports_and_calls_compare_concepts():
    calls = {}

    def fake_search(query, **kwargs):
        return {
            "mode": "keyword_fallback",
            "results": [
                variable("r1", "v1", "VC investment", score=0.9),
                variable("r1", "v2", "Deal value", score=0.8),
                variable("r2", "v3", "Startup funding amount", score=0.7),
                variable("r3", "v4", "Early-stage funding", score=0.4),
                report("r1", "Report A"),
                report("r2", "Report B"),
                report("r3", "Report C"),
            ],
        }

    def fake_compare(query, report_ids=None):
        calls["query"] = query
        calls["report_ids"] = report_ids
        return [
            {"id": "v1", "report_id": "r1", "raw_variable_name": "VC investment", "definition": "Equity VC funding"},
            {"id": "v3", "report_id": "r2", "raw_variable_name": "Startup funding amount", "definition": "Broader funding"},
        ]

    result = compare_concepts_auto(
        "Compare startup funding definitions across reports",
        search_fn=fake_search,
        find_data_fn=fake_find_data,
        compare_fn=fake_compare,
    )

    assert result["status"] == "ok"
    assert calls["report_ids"][:2] == ["r1", "r2"]
    assert result["metadata"]["auto_selected_report_ids"][:2] == ["r1", "r2"]
    assert result["comparison"]["raw_comparisons"]


def test_one_report_returns_insufficient_reports():
    def fake_search(query, **kwargs):
        return {"mode": "keyword_fallback", "results": [variable("r1", "v1", "VC investment"), report("r1", "Report A")]}

    result = compare_concepts_auto("Compare VC investment", search_fn=fake_search, find_data_fn=fake_find_data, compare_fn=lambda *a, **k: [])

    assert result["status"] == "insufficient_reports"
    assert result["comparison"]["comparability"] == "unknown"
    assert "fewer than two reports" in result["comparison"]["summary"]


def test_no_variables_returns_no_results():
    def fake_search(query, **kwargs):
        return {"mode": "keyword_fallback", "results": [report("r1", "Report A")]}

    result = compare_concepts_auto("Compare R&D intensity", search_fn=fake_search, find_data_fn=fake_find_data, compare_fn=lambda *a, **k: [])

    assert result["status"] == "no_results"
    assert result["selected_reports"] == []


def test_public_only_excludes_private_variables():
    def fake_search(query, **kwargs):
        return {
            "mode": "keyword_fallback",
            "results": [
                variable("r1", "v1", "Private VC investment", availability="private", score=0.99),
                variable("r2", "v2", "Public VC investment", availability="public", score=0.5),
                report("r1", "Private Report"),
                report("r2", "Public Report"),
            ],
        }

    result = compare_concepts_auto("Compare VC investment", public_only=True, search_fn=fake_search, find_data_fn=fake_find_data, compare_fn=lambda *a, **k: [])

    assert result["status"] == "insufficient_reports"
    assert result["metadata"]["auto_selected_report_ids"] == ["r2"]


def test_ranking_prefers_more_variables_and_evidence():
    def fake_search(query, **kwargs):
        return {
            "mode": "keyword_fallback",
            "results": [
                variable("r1", "v1", "Funding amount", score=0.3, evidence=True),
                variable("r1", "v2", "Deal count", score=0.3, evidence=True),
                variable("r2", "v3", "Funding", score=0.5, evidence=False),
                report("r1", "Evidence Rich Report"),
                report("r2", "Sparse Report"),
            ],
        }

    result = compare_concepts_auto("Compare funding", search_fn=fake_search, find_data_fn=fake_find_data, compare_fn=lambda *a, **k: [])

    assert result["selected_reports"][0]["report_id"] == "r1"


def test_out_of_scope_item_types_are_excluded():
    def fake_search(query, **kwargs):
        return {
            "mode": "keyword_fallback",
            "results": [
                variable("r1", "v1", "Admin metric", item_type="administrative_metric"),
                variable("r2", "v2", "Funding metric"),
                report("r1", "Admin Report"),
                report("r2", "Funding Report"),
            ],
        }

    result = compare_concepts_auto("Compare funding", search_fn=fake_search, find_data_fn=fake_find_data, compare_fn=lambda *a, **k: [])

    assert result["metadata"]["auto_selected_report_ids"] == ["r2"]


def test_cli_json_outputs_valid_json(monkeypatch, capsys):
    monkeypatch.setattr(
        worker,
        "run_compare_concepts_auto",
        lambda *args, **kwargs: {
            "query": args[0],
            "status": "no_results",
            "selected_reports": [],
            "comparison": {"summary": "No results", "comparability": "unknown"},
            "limitations": [],
            "clarifying_questions": [],
            "metadata": {},
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        ["compare_concepts_auto", "Compare startup funding definitions across reports", "--json"],
    )

    worker.main()

    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "no_results"
