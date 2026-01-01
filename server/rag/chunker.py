from typing import List


def split_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """Simple sliding-window chunker for long texts."""
    if not text:
        return []
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap
    return chunks
