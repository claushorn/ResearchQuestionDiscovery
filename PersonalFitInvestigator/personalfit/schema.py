"""Model-facing output (flat). Quote verification and score caps are applied by code (rules.py)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rqd.structured import api_schema


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Advantage(_M):
    claim: str
    file: str                        # profile file path, as given in <file path="...">
    quote: str                       # verbatim from that file
    why_ml_researcher_lacks_it: str


class Gap(_M):
    gap: str
    how_to_close: str


class FitOutput(_M):
    advantages: list[Advantage] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    interest_match: Literal["high", "medium", "low", "none"]
    interest_quote: str = ""
    personal_advantage: int = Field(ge=0, le=10)
    reasoning: str
    confidence: float = Field(ge=0, le=1)


FIT_SCHEMA = api_schema(FitOutput)
