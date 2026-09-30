from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CANDIDATES = 3
WORD_LIMITS = {"statement": 60, "why_interesting": 30,
               "explicit_unsolved_signal.evidence": 50, "payment_signal.evidence": 50}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UnsolvedSignal(_M):
    present: bool
    evidence: str


class PaymentSignal(_M):
    type: Literal["prize", "grant", "contract", "hiring", "investor_thesis", "none_stated"]
    stated: str
    evidence: str
    deadline: str | None


class Entities(_M):
    organizations: list[str]
    researchers: list[str]


class ExtractedCandidate(_M):
    statement: str
    why_interesting: str
    explicit_unsolved_signal: UnsolvedSignal
    payment_signal: PaymentSignal
    technical_area: list[str] = Field(max_length=3)
    entities: Entities
    referenced_urls: list[str]


class ExtractionResult(_M):
    candidates: list[ExtractedCandidate] = Field(max_length=MAX_CANDIDATES)


_DROP = {"title", "default", "maxLength", "minLength", "maxItems", "minItems"}


def _sanitize(node):
    if isinstance(node, list):
        return [_sanitize(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in _DROP:
            continue
        out[k] = {name: _sanitize(sub) for name, sub in v.items()} if k in ("properties", "$defs") else _sanitize(v)
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


def api_schema(model: type[BaseModel]) -> dict:
    """JSON schema accepted by output_config.format (unsupported constraints removed; Pydantic enforces them)."""
    return _sanitize(model.model_json_schema())


EXTRACTION_SCHEMA = api_schema(ExtractionResult)


def length_violations(c: ExtractedCandidate) -> list[str]:
    values = {"statement": c.statement, "why_interesting": c.why_interesting,
              "explicit_unsolved_signal.evidence": c.explicit_unsolved_signal.evidence,
              "payment_signal.evidence": c.payment_signal.evidence}
    return [k for k, v in values.items() if len(v.split()) > WORD_LIMITS[k]]
