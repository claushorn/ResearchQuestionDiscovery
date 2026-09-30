"""Model-facing output (flat). Scores the earlier stages own are copied by code, not asked for here."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rqd.structured import api_schema

Level = Literal["high", "medium", "low"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_M):
    title: str
    url: str
    quote: str  # verbatim text read on that page


class OGOutput(_M):
    title_question: str                       # "Can X be learned despite Y?"
    novelty_score: int | None = Field(default=None, ge=0, le=10)         # null when novelty was not checked / unclear
    novelty_reasoning: str
    economic_value_score: int | None = Field(default=None, ge=0, le=10)  # null when economic value was not assessed
    value_reasoning: str
    tractability_score: int = Field(ge=0, le=10)
    tractability_reasoning: str
    tractability_confidence: float = Field(ge=0, le=1)
    asymmetric_upside: Level
    upside_reasoning: str
    engagement_consulting: Level
    engagement_research: Level
    engagement_startup: Level
    engagement_employment: Level
    why_unsolved: str
    current_best_approach: str
    what_we_could_test: str
    first_experiment: str
    first_experiment_hours: float = Field(gt=0)       # an assumption, labelled as such in the brief
    first_experiment_compute_usd: float = Field(ge=0)
    if_successful: str
    if_failed: str
    thesis: str                                       # why this could be worth spending 10 hours investigating
    next_step: Literal["investigate", "contact"]
    next_step_reason: str
    evidence: list[Evidence] = Field(default_factory=list)


OG_SCHEMA = api_schema(OGOutput)
