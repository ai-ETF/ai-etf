from typing import List, Dict
import math


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    return math.sqrt(sum(x * x for x in a))


def cosine(a, b):
    na = _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


class Retriever:
    def __init__(self, embedding_repo):
        self.embedding_repo = embedding_repo

    def retrieve(self, query_vector: List[float], top_k: int = 5, doc_id: str = None) -> List[Dict]:
        # embedding_repo should expose query_all() returning dicts with 'vector' and 'text'
        rows = self.embedding_repo.query_all(doc_id=doc_id)
        scored = []
        for r in rows:
            v = r.get("vector")
            score = cosine(query_vector, v)
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [dict(score=s, **r) for s, r in scored[:top_k]]
