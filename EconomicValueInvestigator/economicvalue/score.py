"""Free, deterministic signals from money SourceScout already collected for a problem's sources."""
from collections import Counter

from economicvalue.money import parse_amounts, to_usd

_TIER_ORDER = "ABCDE"
_COMMITTED = ("grant", "prize", "contract")


def default_currency(source_id: str, defaults: dict[str, str]) -> str | None:
    return next((cur for prefix, cur in defaults.items() if source_id.startswith(prefix)), None)


def score_problem(record: dict, rates: dict[str, float], defaults: dict[str, str]) -> dict:
    committed, salaries, unparsed = [], [], []
    for s in record["sources"]:
        ps = s["payment_signal"]
        stated = (ps.get("stated") or "").strip()
        amounts = parse_amounts(stated, default_currency(s["source_id"], defaults))
        usd = [r for r in (to_usd(m, rates) for m in amounts) if r is not None]
        if stated and not usd:
            unparsed.append(f"{s['source_id']}: {stated}")
        if ps["type"] in _COMMITTED:
            committed += [high for _, high in usd]
        elif ps["type"] == "hiring":
            salaries += [x for pair in usd for x in pair]
    deadlines = sorted(str(s["payment_signal"]["deadline"]) for s in record["sources"] if s["payment_signal"].get("deadline"))
    return {"problem_id": record["problem_id"], "statement": record["problem"]["precise_statement"],
            "sources": len(record["sources"]), "distinct_source_ids": len({s["source_id"] for s in record["sources"]}),
            "best_tier": min((s["tier"] for s in record["sources"]), key=_TIER_ORDER.index),
            "payment_types": dict(sorted(Counter(s["payment_signal"]["type"] for s in record["sources"]).items())),
            "max_committed_usd": max(committed) if committed else None,
            "salary_range_usd": [min(salaries), max(salaries)] if salaries else None,
            "next_deadline": deadlines[0] if deadlines else None, "unparsed_amounts": unparsed}


def score_all(records: list[dict], rates: dict[str, float], defaults: dict[str, str]) -> list[dict]:
    scores = [score_problem(r, rates, defaults) for r in records]
    return sorted(scores, key=lambda s: (-(s["max_committed_usd"] or 0), -s["sources"], s["problem_id"]))
