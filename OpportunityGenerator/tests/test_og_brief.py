from og_testing import ev, fit, novelty, og_output, problem
from opportunitygenerator.brief import render

SECTIONS = ["PROBLEM", "WHY THIS MAY BE UNSOLVED", "CURRENT BEST APPROACH", "STRONGEST COUNTEREVIDENCE",
            "ECONOMIC BENEFICIARY", "WHY CLAUS?", "WHAT WE COULD TEST", "ESTIMATED FIRST EXPERIMENT", "IF SUCCESSFUL",
            "IF FAILED", "CONFIDENCE", "OPPORTUNITY PROFILE", "THESIS", "RECOMMENDATION"]


def record(recommendation="investigate", **profile_over):
    o = og_output()
    return {"id": "OPP-0042", "problem_id": "prob-a", "title": o["title_question"],
            "opportunity_profile": {"novelty": 8, "economic_value": 7, "tractability": 6, "personal_advantage": 9,
                                    "asymmetric_upside": "high",
                                    "likely_engagement": {"consulting": "high", "research": "high", "startup": "medium",
                                                          "employment": "low"}} | profile_over,
            "confidence": {"novelty": 0.71, "value": 0.63, "tractability": 0.58, "fit": 0.9},
            "thesis": o["thesis"], "recommendation": recommendation, "recommendation_reason": "cheap test",
            "brief_sections": {k: o[k] for k in ("why_unsolved", "current_best_approach", "what_we_could_test",
                                                  "first_experiment", "if_successful", "if_failed")}
                             | {"first_experiment_hours": 6, "first_experiment_compute_usd": 30}}


def test_all_sections_in_order_with_upstream_content():
    b = render(record(), problem(), fit(), novelty(), ev(), "Claus")
    positions = [b.index(s) for s in SECTIONS]
    assert positions == sorted(positions)
    assert "OPP-0042" in b and "CAN TRADING POLICIES BE LEARNED DESPITE REGIME SHIFTS?" in b
    assert "Learn robust trading policies" in b and "Large funds may already solve this internally." in b
    assert "systematic funds" in b and "80,000,000–320,000,000 USD/year" in b and "Head of Quant Research" in b
    assert "built a live futures trading system alone (project_notes.md)" in b
    assert "~6 hours" in b and "~$30 compute" in b and "assumption" in b
    assert "Novelty       0.71" in b and "Fit           0.90" in b
    assert "novelty 8/10" in b and "consulting: high" in b
    assert "[ ] Ignore\n[x] Investigate\n[ ] Contact someone" in b


def test_missing_novelty_and_ev_are_stated_never_none():
    rec = record(novelty=None, economic_value=None)
    rec["confidence"] |= {"novelty": None, "value": None}
    b = render(rec, problem(), fit(), None, None, "Claus")
    assert "not checked: run noveltyinvestigator" in b and "not assessed: run economicvalue" in b
    assert "None" not in b and "Novelty       —" in b and "novelty unknown" in b


def test_unknown_potential_value_and_other_recommendations():
    b = render(record("contact"), problem(), fit(), novelty(), ev(potential="unknown"), "Claus")
    assert "potential value unknown" in b and "[x] Contact someone" in b
    assert "[x] Ignore" in render(record("ignore"), problem(), fit(), novelty(), ev(), "Claus")
