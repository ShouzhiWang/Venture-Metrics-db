import argparse
from uuid import UUID

from app.agents.codebook_extractor import extract_codebook_candidates
from app.db.connection import get_engine
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.variables import VariableRepository
from app.utils.logging import configure_logging


def generate_codebook(report_id: UUID) -> int:
    engine = get_engine()
    with engine.begin() as connection:
        chunk_repo = ChunkRepository(connection)
        variable_repo = VariableRepository(connection)
        chunks = chunk_repo.list_by_report(report_id)
        candidates = extract_codebook_candidates(chunks)
        for candidate in candidates:
            variable_repo.create_report_variable(candidate)
        return len(candidates)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate placeholder variable codebook entries for one report.")
    parser.add_argument("--report-id", type=UUID, required=True)
    args = parser.parse_args()
    configure_logging()
    count = generate_codebook(args.report_id)
    if count:
        print(f"Generated {count} report variable candidates for {args.report_id}")
    else:
        print(f"No obvious variable patterns found for {args.report_id}; LLM extraction is needed.")


if __name__ == "__main__":
    main()
