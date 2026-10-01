"""Problem records: ProblemExtractor/problems/<problem-id>.yaml (one per merged problem)."""
from datetime import date

from problemextractor.schema import PEOutput
from rqd.timeutil import deadline_summary

TIER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


def best_tier(record: dict) -> str:
    return min((s["tier"] for s in record["sources"]), key=TIER_RANK.get)


PAYMENT_TYPE_LABELS = {"company_investment": "company", "investor_thesis": "investor thesis"}


def payment_label(signal: dict) -> str:
    """`type: stated` (e.g. "grant: $1.5M", "company: tisix.io"), the type alone when nothing is stated, "-" for none."""
    if signal["type"] == "none_stated":
        return "-"
    label = PAYMENT_TYPE_LABELS.get(signal["type"], signal["type"])
    return f"{label}: {signal['stated']}" if signal.get("stated") else label


def best_payment(record: dict) -> str:
    """The first source's payment signal that states something, else the first typed one, else "-"."""
    signals = [s["payment_signal"] for s in record["sources"] if s["payment_signal"]["type"] != "none_stated"]
    stated = [p for p in signals if p.get("stated")]
    return payment_label(stated[0] if stated else signals[0]) if signals else "-"


def due_passed(record: dict, on: date) -> bool:
    return deadline_summary([s["payment_signal"].get("deadline") for s in record["sources"]], on)[1]


# `problemextractor list --sort`: most sources first (then best tier), or best tier first (then most sources)
SORT_KEYS = {"sources": lambda r: (-len(r["sources"]), TIER_RANK[best_tier(r)]),
             "tier": lambda r: (TIER_RANK[best_tier(r)], -len(r["sources"]))}


def problem_id_for(candidate_id: str) -> str:
    """Stable id derived from the first candidate that stated the problem."""
    return "prob-" + candidate_id.removeprefix("cand-")


def source_entry(candidate: dict) -> dict:
    ps = candidate["payment_signal"]
    return {"candidate_id": candidate["candidate_id"], "source_id": candidate["source_id"],
            "tier": candidate["source"]["tier"], "url": candidate["source"]["url"],
            "title": candidate["source"]["title"],
            "payment_signal": {"type": ps["type"], "stated": ps.get("stated", ""), "deadline": ps.get("deadline")}}


def new_record(problem_id: str, candidate: dict, out: PEOutput, evidence_verified: bool, extracted_with: dict) -> dict:
    fields = out.extracted()
    fields["unsolvedness"]["evidence_verified"] = evidence_verified
    return {"problem_id": problem_id, "revision": 1, **fields, "sources": [source_entry(candidate)],
            "merge_log": [{"candidate_id": candidate["candidate_id"], "decision": "new",
                           "reason": out.merge_reason, "extracted": out.extracted()}],
            "extracted_with": extracted_with}


def merge_into(record: dict, candidate: dict, out: PEOutput, evidence_verified: bool | None,
               extracted_with: dict) -> dict:
    """Pool the candidate into an existing problem. The record's text is kept; this candidate's extraction is
    preserved in the merge log so a later stage can re-synthesise."""
    extracted = out.extracted()
    extracted["unsolvedness"]["evidence_verified"] = evidence_verified
    record = {**record, "revision": record["revision"] + 1,
              "sources": [*record["sources"], source_entry(candidate)],
              "merge_log": [*record["merge_log"], {"candidate_id": candidate["candidate_id"], "decision": "merged",
                                                    "reason": out.merge_reason, "extracted": extracted,
                                                    "at": extracted_with["at"]}]}
    return record
