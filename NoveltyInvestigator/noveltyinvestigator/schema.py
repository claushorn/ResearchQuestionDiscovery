"""Novelty Investigator output: the user's format, extended with the six questions and cited evidence.

The model-facing schema is flat (one list of flat `closest_work` objects): nested objects made `claude -p`
reject structured outputs as unparseable JSON in the Problem Extractor (3/10, measured 2026-09-30).
Verification status, search counts and costs are NOT model output; code derives them.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rqd.structured import api_schema

Answer = Literal["yes", "no", "partially", "unclear"]
CHECKS = ("already_solved", "same_problem_paper", "merely_implementation_issue", "obvious_baseline",
          "obvious_approaches_tried")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Work(_M):
    title: str
    url: str
    year: int | None = None
    kind: Literal["paper", "repo", "benchmark", "patent", "report", "company"]
    quote: str  # verbatim text read on that page
    how_close: str


class NIOutput(_M):
    novelty_status: Literal["likely_open", "partially_solved", "solved", "unclear"]
    already_solved: Answer
    already_solved_reasoning: str
    already_solved_evidence: list[int] = Field(default_factory=list)  # 1-based numbers into closest_work
    same_problem_paper: Answer
    same_problem_paper_reasoning: str
    same_problem_paper_evidence: list[int] = Field(default_factory=list)
    merely_implementation_issue: Answer
    merely_implementation_issue_reasoning: str
    merely_implementation_issue_evidence: list[int] = Field(default_factory=list)
    obvious_baseline: Answer
    obvious_baseline_description: str = ""
    obvious_baseline_reasoning: str
    obvious_baseline_evidence: list[int] = Field(default_factory=list)
    obvious_approaches_tried: Answer
    obvious_approaches_tried_reasoning: str
    obvious_approaches_tried_evidence: list[int] = Field(default_factory=list)
    closest_work: list[Work]
    difference_from_closest_work: str
    strongest_counterargument: str
    confidence: float = Field(ge=0, le=1)


NI_SCHEMA = api_schema(NIOutput)


def to_record_fields(out: NIOutput) -> dict:
    """The model's answer in the record's (user-defined, nested) format."""
    checks = {}
    for name in CHECKS:
        checks[name] = {"answer": getattr(out, name), "reasoning": getattr(out, f"{name}_reasoning"),
                        "evidence": getattr(out, f"{name}_evidence")}
    checks["obvious_baseline"] = {"answer": out.obvious_baseline, "baseline": out.obvious_baseline_description,
                                  "reasoning": out.obvious_baseline_reasoning, "evidence": out.obvious_baseline_evidence}
    return {"novelty": {"status": out.novelty_status}, "checks": checks,
            "closest_work": [w.model_dump() for w in out.closest_work],
            "difference_from_closest_work": out.difference_from_closest_work,
            "strongest_counterargument": out.strongest_counterargument, "confidence": out.confidence}
