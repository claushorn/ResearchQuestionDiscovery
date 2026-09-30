"""TF-IDF cosine shortlist of existing problems for a new candidate (deterministic, no dependencies)."""
import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "are", "was", "were", "been", "have", "has",
         "its", "their", "than", "then", "such", "which", "while", "when", "where", "not", "can", "could", "should",
         "would", "will", "using", "use", "via", "per", "over", "under", "between", "across", "based"}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP]


def shortlist(query: str, docs: dict[str, str], k: int) -> list[str]:
    """Ids of the k documents most similar to `query` (score > 0), ties broken by id."""
    if not docs:
        return []
    bags = {pid: Counter(_tokens(t)) for pid, t in docs.items()}
    q = Counter(_tokens(query))
    n = len(bags) + 1
    df = Counter(w for bag in [*bags.values(), q] for w in bag)
    idf = {w: math.log((1 + n) / (1 + d)) + 1 for w, d in df.items()}

    def vec(bag: Counter) -> dict[str, float]:
        return {w: c * idf[w] for w, c in bag.items()}

    def cos(a: dict, b: dict) -> float:
        dot = sum(v * b.get(w, 0.0) for w, v in a.items())
        na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    qv = vec(q)
    scored = [(cos(qv, vec(bag)), pid) for pid, bag in bags.items()]
    return [pid for score, pid in sorted(scored, key=lambda x: (-x[0], x[1])) if score > 0][:k]
