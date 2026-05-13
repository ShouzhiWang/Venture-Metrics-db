import argparse
import json
from uuid import UUID

from app.agents.codebook_extractor import HybridCodebookExtractor, MockLLMCodebookExtractor
from app.db.connection import get_engine
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.variables import VariableRepository
from app.utils.logging import configure_logging


def generate_codebook(
    report_id: UUID,
    *,
    top_k: int = 40,
    use_mock_llm: bool = False,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict:
    engine = get_engine()
    with engine.begin() as connection:
        chunk_repo = ChunkRepository(connection)
        variable_repo = VariableRepository(connection)
        chunks = chunk_repo.list_by_report(report_id)
        extractor = HybridCodebookExtractor(
            llm_extractor=MockLLMCodebookExtractor() if use_mock_llm else None,
            top_k=top_k,
        )
        variables = extractor.extract(report_id, chunks)

        if dry_run:
            return {"summary": extractor.last_summary, "variables": [variable.model_dump(mode="json") for variable in variables]}

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
            **extractor.last_summary,
            "existing_duplicates_skipped": len(variables) - len(to_insert),
            "inserted": len(inserted),
        }
        return {"summary": summary, "variables": [variable.model_dump(mode="json") for variable in to_insert]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate variable codebook entries for one report.")
    parser.add_argument("--report-id", type=UUID, required=True)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--use-mock-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = generate_codebook(
        args.report_id,
        top_k=args.top_k,
        use_mock_llm=args.use_mock_llm,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
        return
    summary = result["summary"]
    print(
        "Codebook generation complete: "
        f"candidate_chunks={summary.get('candidate_chunks', 0)} "
        f"rule_based_variables={summary.get('rule_based_variables', 0)} "
        f"llm_variables={summary.get('llm_variables', 0)} "
        f"inserted={summary.get('inserted', 0)} "
        f"needs_review={summary.get('needs_review', 0)} "
        f"private={summary.get('private', 0)}"
    )


if __name__ == "__main__":
    main()
