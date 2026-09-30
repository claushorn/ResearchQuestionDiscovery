"""Model-facing outputs (flat: lists of flat objects only). Verification and headroom are computed by code; numbers
are only kept when a verified quote (or the scraped leaderboard) states them."""
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


class BaselineOutput(_M):
    evidence: list[Evidence]
    baseline: float | None = None  # the organisers' benchmark score on the leaderboard metric, if found
    evidence_index: int = 0        # 1-based number of the evidence entry whose quote states it
    reasoning: str


BASELINE_SCHEMA = api_schema(BaselineOutput)


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
