import hashlib
from typing import List


class Embedder:
    """Deterministic lightweight embedder.

    NOTE: This is a placeholder. Replace with a real embedding model.
    """

    def __init__(self, dim: int = 128):
        self.dim = dim

    def _hash_vector(self, text: str) -> List[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = []
        for i in range(self.dim):
            byte = h[i % len(h)]
            # map 0-255 to -1..1
            vec.append((byte / 255.0) * 2 - 1)
        return vec

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._hash_vector(t) for t in texts]

    def embed_text(self, text: str) -> List[float]:
        return self._hash_vector(text)
