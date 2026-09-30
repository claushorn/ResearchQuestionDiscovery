"""The Problem Extractor's structured output (user-defined format + merge decision).

Fields a document often does not state default to "not stated": omitted fields must not trigger a
`claude -p` structured-output retry (measured in SourceScout: ~2x tokens), and PE must never invent them.
"""
from pydantic import BaseModel, ConfigDict

from rqd.structured import api_schema

NOT_STATED = "not stated"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProblemText(_M):
    precise_statement: str


class CurrentState(_M):
    known_solution: str = NOT_STATED


class Failure(_M):
    what_current_methods_cannot_do: str = NOT_STATED


class Unsolvedness(_M):
    explicit: bool
    explicit_evidence: str = ""  # verbatim quote, required when explicit
    inferred: bool = False


class PEOutput(_M):
    merge_with: str | None = None  # an id from the offered shortlist, or null for a new problem
    merge_reason: str = ""
    problem: ProblemText
    current_state: CurrentState = CurrentState()
    failure: Failure = Failure()
    desired_capability: str
    why_it_matters: str
    unsolvedness: Unsolvedness

    def extracted(self) -> dict:
        """The six user-defined sections, as extracted."""
        return self.model_dump(include={"problem", "current_state", "failure", "desired_capability",
                                        "why_it_matters", "unsolvedness"})


PE_SCHEMA = api_schema(PEOutput)
