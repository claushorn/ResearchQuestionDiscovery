import pytest
from pydantic import ValidationError

from pe_testing import candidate, pe_output
from problemextractor.records import ProblemStore, merge_into, new_record, problem_id_for
from problemextractor.schema import PE_SCHEMA, PEOutput

W = {"model": "m", "run_id": "R1", "output_tokens": 300, "at": "2026-09-30T13:00:00+00:00"}


def test_new_record_has_the_six_sections_sources_and_log():
    c = candidate()
    rec = new_record(problem_id_for(c["candidate_id"]), c, PEOutput.model_validate(pe_output()), True, W)
    assert rec["problem_id"] == "prob-" + c["candidate_id"].removeprefix("cand-") and rec["revision"] == 1
    assert rec["problem"]["precise_statement"].startswith("Plan long-horizon")
    assert rec["current_state"]["known_solution"] == "not stated"
    assert rec["unsolvedness"] == {"explicit": True, "explicit_evidence": "remains an open challenge", "inferred": False,
                                   "evidence_verified": True}
    assert rec["sources"][0] | {} == {"candidate_id": c["candidate_id"], "source_id": "grants-gov-ml", "tier": "A",
                                      "url": "https://g.example/0", "title": "Call 0",
                                      "payment_signal": {"type": "grant", "stated": "$1.5M", "deadline": "2026-12-01"}}
    assert rec["merge_log"][0]["decision"] == "new" and rec["extracted_with"] == W


def test_merge_appends_source_keeps_text_and_logs_extraction():
    c0, c1 = candidate(0), candidate(1, source_id="greenhouse-acme", tier="B")
    rec = new_record("prob-x", c0, PEOutput.model_validate(pe_output()), True, W)
    out1 = PEOutput.model_validate(pe_output(merge_with="prob-x", statement="A differently worded statement."))
    merged = merge_into(rec, c1, out1, W)
    assert merged["revision"] == 2 and [s["tier"] for s in merged["sources"]] == ["A", "B"]
    assert merged["problem"]["precise_statement"].startswith("Plan long-horizon")
    assert merged["merge_log"][1]["decision"] == "merged" and merged["merge_log"][1]["reason"] == "same capability"
    assert merged["merge_log"][1]["extracted"]["problem"]["precise_statement"] == "A differently worded statement."


def test_store_roundtrip_and_listing(tmp_path):
    st = ProblemStore(tmp_path / "problems")
    rec = new_record("prob-a", candidate(), PEOutput.model_validate(pe_output()), False, W)
    st.save(rec)
    assert st.load("prob-a") == rec and [r["problem_id"] for r in st.all()] == ["prob-a"]


def test_omitted_fields_default_to_not_stated_and_schema_is_structured_output_ready():
    out = PEOutput.model_validate({"precise_statement": "s", "desired_capability": "d", "why_it_matters": "w",
                                   "unsolved_explicit": False})
    assert out.extracted()["current_state"] == {"known_solution": "not stated"} and out.merge_with is None
    assert PE_SCHEMA["additionalProperties"] is False and "merge_with" not in PE_SCHEMA["required"]
    with pytest.raises(ValidationError):
        PEOutput.model_validate({"desired_capability": "d", "why_it_matters": "w", "unsolved_explicit": False})


def test_model_facing_schema_is_flat_because_nested_objects_break_claude_p_tool_calls():
    # measured 2026-09-30: 3/10 PE calls were rejected ("could not be parsed as JSON") inside nested objects
    assert all(p.get("type") != "object" and "$ref" not in p for p in PE_SCHEMA["properties"].values())
    assert "$defs" not in PE_SCHEMA
