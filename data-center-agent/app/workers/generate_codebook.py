import argparse
import json
from uuid import UUID

from app.agents.content_quality import ContentQualityResult, classify_content_quality, should_skip_codebook
from app.agents.codebook_extractor import HybridCodebookExtractor, MockLLMCodebookExtractor
from app.db.connection import get_engine
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.reports import ReportRepository
from app.db.repositories.sources import SourceRepository
from app.db.repositories.variables import VariableRepository
from app.utils.logging import configure_logging


def generate_codebook(
    report_id: UUID,
    *,
    top_k: int = 40,
    use_mock_llm: bool = False,
    dry_run: bool = False,
    overwrite: bool = False,
    force: bool = False,
) -> dict:
    engine = get_engine()
    with engine.begin() as connection:
        chunk_repo = ChunkRepository(connection)
        report_repo = ReportRepository(connection)
        source_repo = SourceRepository(connection)
        variable_repo = VariableRepository(connection)
        report = report_repo.get(report_id)
        source = source_repo.get(report["source_id"]) if report and report.get("source_id") else None
        chunks = chunk_repo.list_by_report(report_id)
        quality = _effective_quality(chunks, report, source)
        skip, reason = should_skip_codebook(quality, force=force)
        if skip:
            summary = {
                "skipped": True,
                "skip_reason": reason,
                "content_quality": quality.source_resolution_status,
                "extraction_eligibility": quality.extraction_eligibility,
                "chunk_count": quality.chunk_count,
                "total_characters": quality.total_characters,
                "strong_keyword_score": quality.strong_keyword_score,
                "candidate_chunks": 0,
                "rule_based_variables": 0,
                "llm_variables": 0,
                "final_variables": 0,
                "inserted": 0,
            }
            return {"summary": summary, "variables": []}

        # Determine if this is a conditional extraction (all vars → needs_review)
        is_conditional = quality.extraction_eligibility == "eligible_conditional"

        extractor = HybridCodebookExtractor(
            llm_extractor=MockLLMCodebookExtractor() if use_mock_llm else None,
            top_k=top_k,
        )
        variables = extractor.extract(report_id, chunks)

        # If conditional, force all variables to needs_review
        if is_conditional:
            variables = [
                variable.model_copy(update={
                    "review_status": "needs_review",
                    "metadata": {
                        **variable.metadata,
                        "quality_forced_needs_review": True,
                        "conditional_reason": quality.eligibility_reason,
                    },
                })
                for variable in variables
            ]

        extraction_summary = {
            **extractor.last_summary,
            "skipped": False,
            "content_quality": quality.source_resolution_status,
            "extraction_eligibility": quality.extraction_eligibility,
            "strong_keyword_score": quality.strong_keyword_score,
            "strong_keyword_hits": quality.strong_keyword_hits,
            "chunk_count": quality.chunk_count,
            "total_characters": quality.total_characters,
        }

        if dry_run:
            return {"summary": extraction_summary, "variables": [variable.model_dump(mode="json") for variable in variables]}

        if overwrite:
            variable_repo.delete_report_variables_by_report(report_id)
            existing = []
        else:
            existing = variable_repo.get_report_variables_by_report(report_id)

        existing_keys = {
            (
                str(row.get("report_id")),
                (row.get("raw_variable_name") or "").strip().lower(),
                str(row.get("evidence_chunk_id")),
            )
            for row in existing
        }

        to_insert = [
            variable
            for variable in variables
            if (str(variable.report_id), variable.raw_variable_name.strip().lower(), str(variable.evidence_chunk_id))
            not in existing_keys
        ]
        inserted = variable_repo.insert_many_report_variables(to_insert)
        summary = {
            **extraction_summary,
            "existing_duplicates_skipped": len(variables) - len(to_insert),
            "inserted": len(inserted),
        }
        return {"summary": summary, "variables": [variable.model_dump(mode="json") for variable in to_insert]}


def _effective_quality(chunks: list[dict], report: dict | None, source: dict | None) -> ContentQualityResult:
    computed = classify_content_quality(
        chunks,
        source_type=source.get("source_type") if source else None,
        crawl_status=source.get("crawl_status") if source else None,
    )
    citation_info = (report or {}).get("citation_info") or {}
    stored = citation_info.get("content_quality") if isinstance(citation_info, dict) else None
    if isinstance(stored, dict) and stored.get("label") in {"landing_page_only", "paywalled_or_gated", "js_required", "failed"}:
        return ContentQualityResult(
            source_resolution_status=stored["label"],
            resolution_reason=stored.get("reason") or computed.resolution_reason,
            extraction_eligibility="ineligible_gated",
            eligibility_reason=f"stored quality: {stored['label']}",
            chunk_count=computed.chunk_count,
            total_characters=computed.total_characters,
            strong_keyword_score=computed.strong_keyword_score,
            strong_keyword_hits=computed.strong_keyword_hits,
            metadata={"stored": stored, "computed": computed.metadata},
        )
    return computed


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate variable codebook entries for one report.")
    parser.add_argument("--report-id", type=UUID, required=True)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--use-mock-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = generate_codebook(
        args.report_id,
        top_k=args.top_k,
        use_mock_llm=args.use_mock_llm,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        force=args.force,
    )
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
        return
    summary = result["summary"]
    if summary.get("skipped"):
        print(
            "Codebook generation skipped: "
            f"reason={summary.get('skip_reason')} "
            f"content_quality={summary.get('content_quality')} "
            f"extraction_eligibility={summary.get('extraction_eligibility')} "
            f"chunks={summary.get('chunk_count')} "
            f"characters={summary.get('total_characters')}"
        )
        return
    print(
        "Codebook generation complete: "
        f"candidate_chunks={summary.get('candidate_chunks', 0)} "
        f"rule_based_variables={summary.get('rule_based_variables', 0)} "
        f"llm_variables={summary.get('llm_variables', 0)} "
        f"inserted={summary.get('inserted', 0)} "
        f"needs_review={summary.get('needs_review', 0)} "
        f"private={summary.get('private', 0)} "
        f"eligibility={summary.get('extraction_eligibility', 'eligible')}"
    )


if __name__ == "__main__":
    main()
