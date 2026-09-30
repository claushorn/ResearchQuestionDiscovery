"""Model-facing output of an economic assessment. Flat (lists of flat objects only): nested objects made
`claude -p` reject structured outputs as unparseable JSON (measured in ProblemExtractor). Amounts appear only in
`estimates`; statuses, verification and potential_value are computed by code (estimates.py)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rqd.structured import api_schema

Quantity = Literal["affected_units", "frequency_per_year", "cost_per_occurrence", "addressable_share",
                   "buyer_count", "annual_spend_per_buyer", "current_cost", "failure_cost"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_M):
    title: str
    url: str
    kind: Literal["award", "prize", "statistic", "filing", "report", "company", "news", "job_posting", "paper", "other"]
    company: str = ""  # required for analogous_company bases
    quote: str         # verbatim text read on that page


class EstimateRow(_M):
    quantity: Quantity
    low: float | None = None
    high: float | None = None
    unit: str
    basis: Literal["source", "analogous_company", "explicit_assumption"]
    evidence: int = 0  # 1-based number into evidence; 0 for explicit assumptions
    assumption: str = ""


class WTPSignal(_M):
    signal: str
    evidence: int


class EVOutput(_M):
    beneficiary_type: str
    beneficiary_description: str
    pain_score: int = Field(ge=1, le=10)
    pain_reasoning: str
    who_has_problem: str
    how_frequently: str
    how_expensive: str
    current_practice: str
    failure_consequence: str
    deployment: Literal["plausible", "difficult", "implausible", "unknown"]
    deployment_barriers: str = ""
    buyer: str
    urgency: Literal["low", "medium", "high", "unknown"]
    urgency_reasoning: str
    evidence: list[Evidence]
    estimates: list[EstimateRow] = Field(default_factory=list)
    willingness_to_pay: list[WTPSignal] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


EV_SCHEMA = api_schema(EVOutput)
TEXT_FIELDS = ("beneficiary_description", "pain_reasoning", "who_has_problem", "how_frequently", "how_expensive",
               "current_practice", "failure_consequence", "deployment_barriers", "buyer", "urgency_reasoning")
