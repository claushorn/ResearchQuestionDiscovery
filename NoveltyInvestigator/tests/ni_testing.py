"""Helpers for NoveltyInvestigator tests (unique module name: no conftest collisions across capabilities)."""


def ni_output(**over) -> dict:
    base = {"novelty_status": "partially_solved",
            "already_solved": "partially", "already_solved_reasoning": "AlphaFold solves most of it", "already_solved_evidence": [1],
            "same_problem_paper": "yes", "same_problem_paper_reasoning": "Jumper et al.", "same_problem_paper_evidence": [1],
            "merely_implementation_issue": "no", "merely_implementation_issue_reasoning": "needs new methods",
            "merely_implementation_issue_evidence": [],
            "obvious_baseline": "yes", "obvious_baseline_description": "run AlphaFold2", "obvious_baseline_reasoning": "public",
            "obvious_baseline_evidence": [1],
            "obvious_approaches_tried": "yes", "obvious_approaches_tried_reasoning": "many groups", "obvious_approaches_tried_evidence": [2],
            "closest_work": [{"title": "AlphaFold2", "url": "https://paper.example/af2", "year": 2021, "kind": "paper",
                              "quote": "predicts protein structures with atomic accuracy", "how_close": "solves it for monomers"},
                             {"title": "RoseTTAFold", "url": "https://paper.example/rf.pdf", "year": 2021, "kind": "paper",
                              "quote": "a three-track network", "how_close": "similar"}],
            "difference_from_closest_work": "complexes remain harder",
            "strongest_counterargument": "the core problem is solved",
            "confidence": 0.8}
    return base | over


def problem_record(pid: str = "prob-abc-r1-0") -> dict:
    return {"problem_id": pid, "revision": 1,
            "problem": {"precise_statement": "Predict 3D protein structure from sequence at near-experimental accuracy."},
            "current_state": {"known_solution": "not stated"}, "failure": {"what_current_methods_cannot_do": "not stated"},
            "desired_capability": "atomic-accuracy structures", "why_it_matters": "drug design",
            "unsolvedness": {"explicit": False, "explicit_evidence": "", "inferred": True, "evidence_verified": None},
            "sources": [{"candidate_id": "cand-abc-r1-0", "source_id": "grants-gov-protein", "tier": "A",
                         "url": "https://g.example/1", "title": "Call 1",
                         "payment_signal": {"type": "grant", "stated": "$1M", "deadline": None}}],
            "merge_log": [], "extracted_with": {"model": "m", "run_id": "R", "output_tokens": 500, "at": "t"}}
