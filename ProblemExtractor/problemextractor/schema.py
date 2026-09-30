"""The Problem Extractor's structured output (user-defined format + merge decision).

The model-facing schema is FLAT: with nested single-field objects, `claude -p` rejected 3 of 10 structured
outputs as unparseable JSON and the model rewrote them (measured 2026-09-30, ~2x tokens). Code maps the flat
fields into the user's nested record format (`extracted()`).

Document fields a document often does not state default to "not stated" (omitted fields must not trigger a
rewrite either). Where the document is silent, the model's own expert knowledge goes into separate
`*_inferred` fields, never into the document fields; NoveltyInvestigator later tests those claims.
"""
from pydantic import BaseModel, ConfigDict

from rqd.structured import api_schema

NOT_STATED = "not stated"


class PEOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merge_with: str | None = None  # an id from the offered shortlist, or null for a new problem
    merge_reason: str = ""
    precise_statement: str
    known_solution: str = NOT_STATED
    known_solution_inferred: str = ""  # the model's own expert assessment, where the document is silent
    what_current_methods_cannot_do: str = NOT_STATED
    what_current_methods_cannot_do_inferred: str = ""
    desired_capability: str
    why_it_matters: str
    unsolved_explicit: bool
    explicit_evidence: str = ""  # verbatim quote, required when unsolved_explicit
    unsolved_inferred: bool = False

    def extracted(self) -> dict:
        """The six user-defined sections, in the record's nested format."""
        return {"problem": {"precise_statement": self.precise_statement},
                "current_state": {"known_solution": self.known_solution,
                                  "known_solution_inferred": self.known_solution_inferred},
                "failure": {"what_current_methods_cannot_do": self.what_current_methods_cannot_do,
                            "what_current_methods_cannot_do_inferred": self.what_current_methods_cannot_do_inferred},
                "desired_capability": self.desired_capability,
                "why_it_matters": self.why_it_matters,
                "unsolvedness": {"explicit": self.unsolved_explicit, "explicit_evidence": self.explicit_evidence,
                                 "inferred": self.unsolved_inferred}}


PE_SCHEMA = api_schema(PEOutput)
