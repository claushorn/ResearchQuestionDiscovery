"""Helpers for ProblemExtractor tests (unique module name: no conftest collisions across capabilities)."""


def candidate(n: int = 0, statement: str = "Long-horizon planning for warehouse robots under uncertainty.",
              tier: str = "A", source_id: str = "grants-gov-ml", quote: str = "remains an open challenge",
              at: str = "2026-09-30T12:00:00+00:00") -> dict:
    item = f"{n:016x}"
    return {"source_id": source_id, "item_id": item, "candidate_id": f"cand-{item}-r1-0", "revision": 1,
            "source": {"url": f"https://g.example/{n}", "title": f"Call {n}", "date": None, "tier": tier,
                       "category": "gov_solicitation"},
            "candidate_problem": {"statement": statement}, "why_interesting": "Agency funds it.",
            "explicit_unsolved_signal": {"present": bool(quote), "evidence": quote},
            "payment_signal": {"type": "grant", "stated": "$1.5M", "evidence": "up to $1.5M", "deadline": "2026-12-01"},
            "technical_area": ["planning"], "entities": {"organizations": ["NSF"], "researchers": []},
            "referenced_urls": [], "evidence_verified": True, "length_violations": [],
            "extracted_with": {"model": "m", "run_id": "R", "output_tokens": 400, "at": at}}


def pe_output(merge_with=None, statement="Plan long-horizon robot tasks under uncertainty.", explicit=True,
              evidence="remains an open challenge", known="not stated") -> dict:
    return {"merge_with": merge_with, "merge_reason": "same capability" if merge_with else "new",
            "problem": {"precise_statement": statement}, "current_state": {"known_solution": known},
            "failure": {"what_current_methods_cannot_do": "plan beyond short horizons"},
            "desired_capability": "reliable long-horizon plans", "why_it_matters": "the agency funds it",
            "unsolvedness": {"explicit": explicit, "explicit_evidence": evidence if explicit else "", "inferred": False}}
