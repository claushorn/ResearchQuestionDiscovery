"""Helpers for OpportunityGenerator tests (unique module name: no conftest collisions)."""


def problem(pid="prob-a", revision=1, statement="Learn robust trading policies despite non-stationary markets."):
    return {"problem_id": pid, "revision": revision, "problem": {"precise_statement": statement},
            "current_state": {"known_solution": "not stated", "known_solution_inferred": "walk-forward retraining"},
            "failure": {"what_current_methods_cannot_do": "not stated", "what_current_methods_cannot_do_inferred": ""},
            "desired_capability": "policies that survive regime shifts", "why_it_matters": "funds lose money at regime shifts",
            "unsolvedness": {"explicit": True, "explicit_evidence": "", "inferred": True, "evidence_verified": True},
            "sources": [], "merge_log": []}


def fit(pid="prob-a", score=9, revision=1, digest="d1", confidence=0.9):
    return {"problem_id": pid, "revision": revision, "problem_revision": 1, "profile_digest": digest,
            "advantages": [{"claim": "built a live futures trading system alone", "file": "project_notes.md",
                            "quote": "Built a live futures trading system alone", "why_ml_researcher_lacks_it": "no live execution",
                            "basis": "profile"}],
            "gaps": [{"gap": "no fund partner", "how_to_close": "contact a prop firm"}],
            "interest_match": {"level": "high", "quote": "sequential decision-making problems"},
            "personal_advantage": {"score": score, "stated_by_model": score, "reasoning": "r", "confidence": confidence},
            "warnings": [], "run": {}, "history": []}


def novelty(pid="prob-a", status="likely_open", confidence=0.71, revision=1):
    return {"problem_id": pid, "revision": revision, "novelty": {"status": status}, "confidence": confidence,
            "strongest_counterargument": "Large funds may already solve this internally.",
            "closest_work": [{"title": "Paper", "url": "https://n.example/p", "quote": "regime shifts degrade policies by 40%",
                              "verification": "verified"}]}


def ev(pid="prob-a", confidence=0.63, revision=1, potential="range"):
    pv = {"low": 80_000_000, "high": 320_000_000, "unit": "USD/year", "status": "supported", "model": "market",
          "basis": []} if potential == "range" else "unknown"
    return {"problem_id": pid, "revision": revision, "confidence": confidence,
            "economic_value": {"beneficiary": {"type": "hedge_fund", "description": "systematic funds"},
                               "buyer": "Head of Quant Research", "potential_value": pv}}


def og_output(**over):
    base = {"title_question": "Can trading policies be learned despite regime shifts?",
            "novelty_score": 8, "novelty_reasoning": "open per the novelty check",
            "economic_value_score": 7, "value_reasoning": "funds pay for robustness",
            "tractability_score": 6, "tractability_reasoning": "public futures data exist", "tractability_confidence": 0.58,
            "asymmetric_upside": "high", "upside_reasoning": "a working method is directly monetisable",
            "engagement_consulting": "high", "engagement_research": "high", "engagement_startup": "medium",
            "engagement_employment": "low",
            "why_unsolved": "regime labels are not observable in real time",
            "current_best_approach": "walk-forward retraining with regime features",
            "what_we_could_test": "whether a regime-conditioned policy beats walk-forward retraining out of sample",
            "first_experiment": "replay 2 years of futures bars with both policies",
            "first_experiment_hours": 6, "first_experiment_compute_usd": 30,
            "if_successful": "consulting or a product for systematic funds", "if_failed": "still measures the regime-shift cost",
            "thesis": "The profile already runs the infrastructure this needs.",
            "next_step": "investigate", "next_step_reason": "a cheap offline test exists",
            "evidence": [{"title": "Data", "url": "https://d.example/futures", "quote": "free historical futures bars since 2010"}]}
    return base | over
