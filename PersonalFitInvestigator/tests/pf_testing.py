"""Helpers for PersonalFitInvestigator tests (unique module name: no conftest collisions). No real profile content."""
from pathlib import Path

from rqd_testing import pdf_bytes

CV = "Jane Doe, Ph.D.\nFounded the displaced-vertices group at the ATLAS experiment.\nBuilt a live futures trading system alone.\n"
CAPS = "capabilities:\n  reinforcement_learning:\n    level: 9\n"
INTERESTS = "sequential decision-making problems\nprotein engineering\n"


def make_profile(directory: Path, pdf_text: str = "Solved the data leakage problem in protein-ligand modeling") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cv.md").write_text(CV, encoding="utf-8")
    (directory / "capabilities.yaml").write_text(CAPS, encoding="utf-8")
    (directory / "interests.yml").write_text(INTERESTS, encoding="utf-8")
    (directory / "cv_long.pdf").write_bytes(pdf_bytes(pdf_text))
    return directory


def problem(pid="prob-a", revision=1, statement="Detect long-lived particles decaying far from the beam line."):
    return {"problem_id": pid, "revision": revision, "problem": {"precise_statement": statement},
            "current_state": {"known_solution": "not stated", "known_solution_inferred": "track-based triggers"},
            "failure": {"what_current_methods_cannot_do": "not stated", "what_current_methods_cannot_do_inferred": ""},
            "desired_capability": "efficient displaced-vertex triggers", "why_it_matters": "new physics reach",
            "unsolvedness": {"explicit": True, "explicit_evidence": "", "inferred": True, "evidence_verified": True},
            "sources": [], "merge_log": []}


def advantage(file="cv.md", quote="Founded the displaced-vertices group at the ATLAS experiment", claim="led the field"):
    return {"claim": claim, "file": file, "quote": quote, "why_ml_researcher_lacks_it": "no detector physics background"}


def fit_output(advantages=None, **over):
    base = {"advantages": [advantage()] if advantages is None else advantages,
            "gaps": [{"gap": "no current detector access", "how_to_close": "collaborate with an LHC group"}],
            "interest_match": "high", "interest_quote": "sequential decision-making problems",
            "personal_advantage": 9, "reasoning": "founded the field's working group", "confidence": 0.8}
    return base | over
