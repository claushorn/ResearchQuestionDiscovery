"""Headroom gate: how much of the gap to the ceiling the winner left open, computed by code from values that
verified quotes state (spec rules). 'unclear' is never 'solved'."""
import math

from challengeinvestigator.schema import HeadroomOutput, Value
from rqd.numbers import figure_in_quote

VERIFIED = ("verified", "verified_row")  # verified_row: a leaderboard row, numbers in one <tr>


def _stated(value: float, quote: str) -> bool:
    """A score may be quoted as a plain number or a percentage (0.871 or 87.1 for '87.1%')."""
    return (figure_in_quote(value, quote, None) or figure_in_quote(value, quote, "%")
            or figure_in_quote(value / 100, quote, "%"))


def _check(v: Value, out: HeadroomOutput, verification: list[str]) -> dict:
    if not math.isfinite(v.value):
        raise ValueError("not a finite number")
    if v.basis == "definition":
        if v.quantity != "ceiling":
            raise ValueError("only a ceiling can rest on the metric's definition")
        if not v.definition.strip():
            raise ValueError("definition basis without the definition stated")
        return {"type": "definition", "definition": v.definition}
    if not 1 <= v.evidence <= len(out.evidence):
        raise ValueError(f"cites evidence {v.evidence}, which does not exist")
    ev = out.evidence[v.evidence - 1]
    status = verification[v.evidence - 1]
    if status not in VERIFIED:
        raise ValueError(f"evidence {v.evidence} is {status}")
    if not _stated(v.value, ev.quote):
        raise ValueError(f"{v.value:g} not in evidence {v.evidence}'s quote")
    return {"type": "source", "url": ev.url, "quote": ev.quote, "verification": status}


def compute(out: HeadroomOutput, verification: list[str], threshold: float) -> dict:
    warnings: list[str] = []
    valid: dict[str, list[tuple[float, dict]]] = {"winner": [], "ceiling": [], "baseline": []}
    for v in out.values:
        try:
            valid[v.quantity].append((v.value, _check(v, out, verification)))
        except ValueError as e:
            warnings.append(f"{v.quantity} {v.value:g} rejected: {e}")
    higher = out.direction == "higher_is_better"
    winner = (max if higher else min)(valid["winner"], key=lambda x: x[0]) if valid["winner"] else None
    ceiling = valid["ceiling"][0] if valid["ceiling"] else None
    baseline = valid["baseline"][0] if valid["baseline"] else None
    normalized, verdict = None, "unclear"
    if winner is None:
        warnings.append("no winner score backed by a verified quote")
    elif ceiling is None:
        warnings.append("no ceiling backed by a verified quote or a stated metric definition")
    else:
        w, c = winner[0], ceiling[0]
        gap = (c - w) if higher else (w - c)
        if baseline is not None:
            scale = (c - baseline[0]) if higher else (baseline[0] - c)
        elif higher:
            scale = c
        else:
            scale = None
            warnings.append("lower-is-better metric without a cited baseline: headroom cannot be scaled")
        if gap < 0:
            warnings.append(f"winner {w:g} is beyond the ceiling {c:g}")
        elif scale is not None and scale <= 0:
            warnings.append(f"non-positive scale {scale:g} (ceiling vs baseline)")
        elif scale is not None:
            normalized = gap / scale
            verdict = "solved" if normalized < threshold - 1e-9 else "headroom"  # 1 - 0.9 is 0.0999...98

    def entry(x, **extra):
        return None if x is None else {"value": x[0], "basis": [x[1]], **extra}
    return {"metric": out.metric, "direction": out.direction,
            "winner": entry(winner, team=out.winner_team), "ceiling": entry(ceiling), "baseline": entry(baseline),
            "normalized_headroom": normalized, "verdict": verdict, "threshold": threshold,
            "reasoning": out.reasoning, "confidence": out.confidence, "warnings": warnings}
