import pytest

from challengeinvestigator.config import MetricBound
from challengeinvestigator.headroom import from_leaderboard, needs_baseline
from challengeinvestigator.leaderboard import Leaderboard

BOUNDS = [MetricBound(match="accuracy", direction="higher_is_better", ceiling=1.0, definition="accuracy is at most 1"),
          MetricBound(match="log loss|centipawn", direction="lower_is_better", ceiling=0.0, definition="a loss is at least 0")]


def lb(metric, scores, baselines=()):
    return Leaderboard(url="https://lb.example", label="final", metric=metric,
                       ranked=[(f"team{i}", s) for i, s in enumerate(scores, 1)], baselines=list(baselines))


def h(board, baseline=None, threshold=0.10):
    return from_leaderboard(board, BOUNDS, threshold, baseline)


def test_lower_is_better_uses_the_strongest_baseline_row():
    r = h(lb("Average Centipawn Loss (ACPL)", [19.369, 23.495], [("gpt", 68.623), ("sft", 71.921)]))
    assert r["direction"] == "lower_is_better" and r["winner"] == {"value": 19.369, "team": "team1"}
    assert r["baseline"]["value"] == 68.623 and r["baseline"]["basis"] == {"type": "leaderboard", "name": "gpt"}
    assert r["ceiling"] == {"value": 0.0, "basis": {"type": "definition", "definition": "a loss is at least 0"}}
    assert r["normalized_headroom"] == pytest.approx(19.369 / 68.623) and r["verdict"] == "headroom"


def test_higher_is_better_without_baseline_relative_to_ceiling():
    r = h(lb("Accuracy", [0.95, 0.9]))
    assert r["normalized_headroom"] == pytest.approx(0.05) and r["verdict"] == "solved"
    assert h(lb("Accuracy", [0.9, 0.8]))["verdict"] == "headroom"  # exactly 10% left


def test_higher_is_better_with_baseline():
    r = h(lb("accuracy", [0.9, 0.8], [("starter", 0.5)]))
    assert r["normalized_headroom"] == pytest.approx(0.2)


def test_metric_without_known_bound_is_unclear():
    r = h(lb("Score", [5.0, 6.0]))
    assert r["verdict"] == "unclear" and r["ceiling"] is None and any("metric_bounds" in w for w in r["warnings"])


def test_rank_order_must_agree_with_the_metric_direction():
    r = h(lb("Accuracy", [0.7, 0.8]))  # ranked ascending: not accuracy as we know it
    assert r["verdict"] == "unclear" and any("rank order" in w for w in r["warnings"])


def test_unsorted_leaderboard_is_unclear():
    r = h(lb("Accuracy", [0.9, 0.7, 0.8]))
    assert r["verdict"] == "unclear" and any("not sorted" in w for w in r["warnings"])


def test_single_row_uses_the_metric_direction():
    assert h(lb("Accuracy", [0.8]))["verdict"] == "headroom"


def test_lower_is_better_without_baseline_needs_one():
    r = h(lb("Log Loss", [0.2532, 0.2731]))
    assert r["verdict"] == "unclear" and needs_baseline(r) and any("baseline" in w for w in r["warnings"])
    looked_up = {"value": 0.6, "basis": {"type": "source", "url": "u", "quote": "q", "verification": "verified"}}
    r = h(lb("Log Loss", [0.2532, 0.2731]), baseline=looked_up)
    assert r["normalized_headroom"] == pytest.approx(0.2532 / 0.6) and not needs_baseline(r)
    assert r["baseline"] == looked_up


def test_winner_worse_than_baseline_is_unclear():
    r = h(lb("Log Loss", [0.7, 0.8], [("benchmark", 0.5)]))
    assert r["verdict"] == "unclear" and r["normalized_headroom"] is None and any("worse than the baseline" in w for w in r["warnings"])


def test_winner_beyond_ceiling_is_unclear():
    r = h(lb("Accuracy (%)", [97.0, 90.0]))
    assert r["verdict"] == "unclear" and any("beyond the ceiling" in w for w in r["warnings"])


def test_top_rows_are_recorded():
    r = h(lb("Accuracy", [0.9 - i / 100 for i in range(15)]))
    assert len(r["leaderboard"]["top"]) == 10 and r["leaderboard"]["top"][0] == {"rank": 1, "team": "team1", "score": 0.9}


@pytest.mark.parametrize("metric, direction", [
    # metric names measured on the real AIcrowd/DrivenData leaderboards (2026-09-30)
    ("Log Loss", "lower_is_better"), ("Agg Log Loss", "lower_is_better"),
    ("Agg Root-mean-square error", "lower_is_better"), ("Root-mean-square error", "lower_is_better"),
    ("Average Root Mean Squared Error", "lower_is_better"), ("Mean Absolute Error", "lower_is_better"),
    ("Normalized MAE", "lower_is_better"), ("Average Centipawn Loss (ACPL)", "lower_is_better"),
    ("Dice coefficient", "higher_is_better"), ("Jaccard index", "higher_is_better"),
    ("Mean Average Precision", "higher_is_better"), ("Macro F1 Score @ 0.75 IoU", "higher_is_better"),
    ("Mean Normalized Reward", "higher_is_better"),
    ("Score", None), ("Weighted Class Score", None), ("See problem description", None), ("CompletedTaskCount", None),
])
def test_configured_metric_bounds_on_measured_metric_names(metric, direction):
    from pathlib import Path
    from challengeinvestigator.config import load_config
    bounds = load_config(Path(__file__).resolve().parents[1] / "config.yaml").metric_bounds
    r = from_leaderboard(lb(metric, [0.5]), bounds, 0.10)
    assert (r["ceiling"] is not None and r["direction"]) == (direction if direction else False)
