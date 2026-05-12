from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.variables import VariableRepository


def keyword_answer(query: str, chunk_repo: ChunkRepository, variable_repo: VariableRepository, limit: int = 5) -> dict:
    return {
        "question": query,
        "mode": "keyword_search_mvp",
        "chunks": chunk_repo.keyword_search(query, limit=limit),
        "variables": variable_repo.keyword_search(query, limit=limit),
        "note": "No LLM synthesis is used yet. Results are direct database matches for review.",
    }
