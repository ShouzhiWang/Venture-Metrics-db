import re


def canonicalize_variable_name(name: str) -> str:
    lowered = name.lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    return lowered.strip("_")


def compare_variable_definitions(_variables: list[dict]) -> list[dict]:
    # TODO: Add embedding similarity and LLM-written difference summaries.
    return []
