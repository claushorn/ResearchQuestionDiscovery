"""Model-facing outputs (flat: lists of flat objects only). Verification, headroom and verdicts are computed by
code; numbers are only kept when a verified quote states them (or, for a ceiling, a stated metric definition)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rqd.structured import api_schema


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_M):
    title: str
    url: str
    kind: Literal["leaderboard", "announcement", "challenge_page", "paper", "repo", "writeup", "discussion", "other"]
    quote: str  # verbatim text read on that page


class Value(_M):
    quantity: Literal["winner", "ceiling", "baseline"]
    value: float
    basis: Literal["source", "definition"]  # definition: only for a ceiling of a bounded metric
    evidence: int = 0                       # 1-based number into evidence for basis source
    definition: str = ""                    # e.g. "accuracy is at most 1.0"


class HeadroomOutput(_M):
    metric: str
    direction: Literal["higher_is_better", "lower_is_better"]
    winner_team: str = ""
    evidence: list[Evidence]
    values: list[Value] = Field(default_factory=list)
    reasoning: str
    confidence: float = Field(ge=0, le=1)


HEADROOM_SCHEMA = api_schema(HeadroomOutput)


class Solution(_M):
    place: int | None = None
    team: str
    title: str
    url: str
    kind: Literal["code", "writeup", "paper", "post"]
    approach: str
    score: float | None = None
    evidence: int  # 1-based number of the evidence entry showing this solution (and its score, if given)


class Idea(_M):
    idea: str
    builds_on: str
    why_it_could_win: str
    risks: str
    effort: Literal["low", "medium", "high"]
    expected_gain_assumption: str = ""  # an explicitly labelled assumption, never a claimed result


class InvestigateOutput(_M):
    evidence: list[Evidence]
    solutions: list[Solution] = Field(default_factory=list)
    ideas: list[Idea] = Field(default_factory=list)
    summary: str


INVESTIGATE_SCHEMA = api_schema(InvestigateOutput)
