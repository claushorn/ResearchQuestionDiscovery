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


def ev_output(estimates=None, evidence=None, **over) -> dict:
    base = {"beneficiary_type": "AI_startup", "beneficiary_description": "teams deploying LLM agents",
            "pain_score": 8, "pain_reasoning": "agents are blocked", "who_has_problem": "AI startups",
            "how_frequently": "every deployment", "how_expensive": "see estimates", "current_practice": "manual review",
            "failure_consequence": "incidents", "deployment": "plausible", "deployment_barriers": "integration",
            "buyer": "CTO / Head_of_Research", "urgency": "medium", "urgency_reasoning": "rising adoption",
            "evidence": evidence if evidence is not None else [
                {"title": "Survey", "url": "https://e.example/1", "kind": "statistic", "company": "",
                 "quote": "2,000 companies deploy agents"},
                {"title": "Acme 10-K", "url": "https://e.example/2", "kind": "filing", "company": "Acme",
                 "quote": "incidents cost us $40,000 each"}],
            "estimates": estimates if estimates is not None else [],
            "willingness_to_pay": [], "confidence": 0.6}
    return base | over


def row(quantity, low, high, unit, basis="source", evidence=1, assumption=""):
    return {"quantity": quantity, "low": low, "high": high, "unit": unit, "basis": basis, "evidence": evidence,
            "assumption": assumption}


FACTORS = [row("affected_units", 2000, 2000, "companies", evidence=1),  # "2,000 companies" is in evidence 1
           row("frequency_per_year", 2, 4, "per year", basis="explicit_assumption", evidence=0,
               assumption="2-4 serious incidents per company per year"),
           row("cost_per_occurrence", 40000, 40000, "USD", basis="analogous_company", evidence=2),
           row("addressable_share", 0.05, 0.1, "share", basis="explicit_assumption", evidence=0,
               assumption="5-10% adopt a solution")]


MARKET = [row("buyer_count", 24, 50, "vendors", basis="explicit_assumption", evidence=0,
              assumption="24-50 specialist vendors"),
          row("annual_spend_per_buyer", 40_000, 40_000, "USD/year", basis="analogous_company", evidence=2),
          row("addressable_share", 0.05, 0.2, "share", basis="explicit_assumption", evidence=0,
              assumption="5-20% of vendors adopt")]
