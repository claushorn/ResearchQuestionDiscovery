"""Headroom gate, computed by code from the scraped final leaderboard: the winner is rank 1, the direction is the
rank order (checked against the metric's known direction), the ceiling comes from the metric's definition in
config (metric_bounds), the baseline from the leaderboard's baseline rows (or a verified lookup). 'unclear' is
never 'solved'."""
import re

from challengeinvestigator.config import MetricBound
from challengeinvestigator.leaderboard import Leaderboard

TOP_ROWS = 10


def _rank_direction(scores: list[float]) -> str | None:
    pairs = list(zip(scores, scores[1:]))
    if all(a >= b for a, b in pairs) and any(a > b for a, b in pairs):
        return "higher_is_better"
    if all(a <= b for a, b in pairs) and any(a < b for a, b in pairs):
        return "lower_is_better"
    return None


def needs_baseline(h: dict) -> bool:
    """Lower-is-better with a winner and a ceiling but no baseline: the gap cannot be scaled without one."""
    return (h["verdict"] == "unclear" and h["direction"] == "lower_is_better" and h["baseline"] is None
            and h["winner"] is not None and h["ceiling"] is not None)


def from_leaderboard(lb: Leaderboard, bounds: list[MetricBound], threshold: float, baseline: dict | None = None) -> dict:
    """`baseline`: a looked-up baseline {value, basis} used when the leaderboard lists none."""
    warnings: list[str] = []
    bound = next((b for b in bounds if re.search(b.match, lb.metric, re.IGNORECASE)), None)
    scores = [s for _, s in lb.ranked]
    by_rank = _rank_direction(scores)
    direction = bound.direction if bound else by_rank
    if bound is None:
        warnings.append(f"metric {lb.metric!r} has no known bound: add it to metric_bounds in config.yaml if its "
                        "definition bounds it")
    elif len(set(scores)) > 1 and by_rank is None:
        warnings.append("leaderboard is not sorted by its score column")
    elif by_rank is not None and by_rank != bound.direction:
        warnings.append(f"rank order says {by_rank} but {lb.metric!r} is {bound.direction}")
    consistent = bound is not None and not warnings
    team, w = lb.ranked[0]
    ceiling = {"value": bound.ceiling, "basis": {"type": "definition", "definition": bound.definition}} if bound else None
    if lb.baselines and direction:
        name, value = (max if direction == "higher_is_better" else min)(lb.baselines, key=lambda x: x[1])
        baseline = {"value": value, "basis": {"type": "leaderboard", "name": name}}  # the strongest: most conservative
    normalized, verdict = None, "unclear"
    if consistent:
        higher = direction == "higher_is_better"
        c = bound.ceiling
        gap = (c - w) if higher else (w - c)
        if baseline is not None:
            scale = (c - baseline["value"]) if higher else (baseline["value"] - c)
        elif higher:
            scale = c
        else:
            scale = None
            warnings.append("lower-is-better metric without a baseline: headroom cannot be scaled")
        if gap < 0:
            warnings.append(f"winner {w:g} is beyond the ceiling {c:g}")
        elif scale is not None and scale <= 0:
            warnings.append(f"non-positive scale {scale:g} (ceiling vs baseline)")
        elif baseline is not None and gap > scale:
            warnings.append(f"winner {w:g} is worse than the baseline {baseline['value']:g}: wrong column or direction?")
        elif scale is not None:
            normalized = gap / scale
            verdict = "solved" if normalized < threshold - 1e-9 else "headroom"  # 1 - 0.9 is 0.0999...98
    return {"metric": lb.metric, "direction": direction,
            "leaderboard": {"url": lb.url, "label": lb.label,
                            "top": [{"rank": i, "team": t, "score": s} for i, (t, s) in enumerate(lb.ranked[:TOP_ROWS], 1)],
                            "baselines": [{"name": n, "score": s} for n, s in lb.baselines]},
            "winner": {"value": w, "team": team}, "ceiling": ceiling, "baseline": baseline,
            "normalized_headroom": normalized, "verdict": verdict, "threshold": threshold, "warnings": warnings}
