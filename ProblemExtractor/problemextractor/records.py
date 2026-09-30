"""Problem records: ProblemExtractor/problems/<problem-id>.yaml (one per merged problem)."""
from problemextractor.schema import PEOutput


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


def merge_into(record: dict, candidate: dict, out: PEOutput, extracted_with: dict) -> dict:
    """Pool the candidate into an existing problem. The record's text is kept; this candidate's extraction is
    preserved in the merge log so a later stage can re-synthesise."""
    record = {**record, "revision": record["revision"] + 1,
              "sources": [*record["sources"], source_entry(candidate)],
              "merge_log": [*record["merge_log"], {"candidate_id": candidate["candidate_id"], "decision": "merged",
                                                    "reason": out.merge_reason, "extracted": out.extracted(),
                                                    "at": extracted_with["at"]}]}
    return record
