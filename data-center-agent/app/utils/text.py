import re


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def count_tokens_rough(text: str) -> int:
    return len(re.findall(r"\S+", text))


def chunk_text(text: str, max_words: int = 450, overlap_words: int = 60) -> list[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []

    chunks: list[str] = []
    step = max(max_words - overlap_words, 1)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + max_words])
        if chunk:
            chunks.append(chunk)
        if start + max_words >= len(words):
            break
    return chunks
