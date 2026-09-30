from ev_testing import problem, source
from economicvalue.score import score_problem

RATES = {"USD": 1.0, "GBP": 1.25}
DEFAULTS = {"grants-gov-": "USD", "aria-": "GBP"}


def test_score_components_from_stored_payment_signals():
    rec = problem(sources=[
        source("grants-gov-ml", "A", "grant", "Award ceiling: 250,000", "2026-12-01"),
        source("aria-programmes", "A", "grant", "nearly £50m", "2026-11-15"),
        source("greenhouse-acme", "B", "hiring", "$212,000 — $339,000 USD"),
        source("greenhouse-acme", "B", "hiring", "$150,000 — $200,000 USD"),
        source("rss-x", "C", "none_stated", ""),
        source("challenge-x", "A", "prize", "a large prize"),
    ])
    s = score_problem(rec, RATES, DEFAULTS)
    assert (s["sources"], s["distinct_source_ids"], s["best_tier"]) == (6, 5, "A")
    assert s["max_committed_usd"] == 62_500_000 and s["salary_range_usd"] == [150_000, 339_000]
    assert s["payment_types"] == {"grant": 2, "hiring": 2, "none_stated": 1, "prize": 1}
    assert s["next_deadline"] == "2026-11-15" and s["unparsed_amounts"] == ["challenge-x: a large prize"]


def test_problem_without_money():
    s = score_problem(problem(sources=[source("rss-x", "C", "none_stated", "")]), RATES, DEFAULTS)
    assert s["max_committed_usd"] is None and s["salary_range_usd"] is None and s["unparsed_amounts"] == []


def test_unknown_tier_does_not_crash():
    s = score_problem(problem(sources=[source("x", "Z", "grant", "$1M")]), RATES, DEFAULTS)
    assert s["best_tier"] == "Z" and s["max_committed_usd"] == 1_000_000
