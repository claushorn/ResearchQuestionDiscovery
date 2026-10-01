from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rqd.structured import api_schema

MAX_CANDIDATES = 3
WORD_LIMITS = {"statement": 60, "why_interesting": 30,
               "explicit_unsolved_signal.evidence": 50, "payment_signal.evidence": 50}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Fields that are often empty are optional: `claude -p` validates structured output after generation and
# makes the model rewrite the whole JSON when a required field is omitted (measured: ~2x output tokens).
class UnsolvedSignal(_M):
    present: bool
    evidence: str = ""


class PaymentSignal(_M):
    type: Literal["prize", "grant", "contract", "hiring", "investor_thesis", "company_investment", "none_stated"]
    stated: str = ""
    evidence: str = ""
    deadline: str | None = None


class Entities(_M):
    organizations: list[str]
    researchers: list[str] = Field(default_factory=list)


class ExtractedCandidate(_M):
    statement: str
    why_interesting: str
    explicit_unsolved_signal: UnsolvedSignal
    payment_signal: PaymentSignal
    technical_area: list[str] = Field(max_length=3)
    entities: Entities
    relevant_links: list[int] = Field(default_factory=list)  # numbers from the document's link list


class ExtractionResult(_M):
    candidates: list[ExtractedCandidate] = Field(max_length=MAX_CANDIDATES)





EXTRACTION_SCHEMA = api_schema(ExtractionResult)


def length_violations(c: ExtractedCandidate) -> list[str]:
    values = {"statement": c.statement, "why_interesting": c.why_interesting,
              "explicit_unsolved_signal.evidence": c.explicit_unsolved_signal.evidence,
              "payment_signal.evidence": c.payment_signal.evidence}
    return [k for k, v in values.items() if len(v.split()) > WORD_LIMITS[k]]
