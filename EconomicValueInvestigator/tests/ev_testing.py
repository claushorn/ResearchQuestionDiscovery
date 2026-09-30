"""Helpers for EconomicValueInvestigator tests (unique module name: no conftest collisions)."""


def source(source_id="grants-gov-ml", tier="A", ptype="grant", stated="Award ceiling: 250,000", deadline=None):
    return {"candidate_id": f"cand-{source_id}", "source_id": source_id, "tier": tier, "url": "https://g.example/1",
            "title": "Call", "payment_signal": {"type": ptype, "stated": stated, "deadline": deadline}}


def problem(pid="prob-a", sources=None, statement="Plan long-horizon robot tasks under uncertainty."):
    return {"problem_id": pid, "revision": 1, "problem": {"precise_statement": statement},
            "current_state": {"known_solution": "not stated", "known_solution_inferred": ""},
            "failure": {"what_current_methods_cannot_do": "not stated", "what_current_methods_cannot_do_inferred": ""},
            "desired_capability": "reliable plans", "why_it_matters": "agency funds it",
            "unsolvedness": {"explicit": False, "explicit_evidence": "", "inferred": True, "evidence_verified": None},
            "sources": sources if sources is not None else [source()], "merge_log": [],
            "extracted_with": {"model": "m", "run_id": "R", "output_tokens": 900, "at": "t"}}
