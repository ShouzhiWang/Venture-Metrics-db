import argparse
import json

from app.agents.chatbot import keyword_answer
from app.db.connection import get_engine
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.variables import VariableRepository
from app.utils.logging import configure_logging


def ask(question: str, limit: int = 5) -> dict:
    engine = get_engine()
    with engine.begin() as connection:
        chunk_repo = ChunkRepository(connection)
        variable_repo = VariableRepository(connection)
        return keyword_answer(question, chunk_repo, variable_repo, limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Keyword search over parsed chunks and variable codebooks.")
    parser.add_argument("question")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    configure_logging()
    result = ask(args.question, args.limit)
    print(json.dumps(result, default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
