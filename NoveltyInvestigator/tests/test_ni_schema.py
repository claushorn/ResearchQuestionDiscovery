import pytest
from pydantic import ValidationError

from ni_testing import ni_output
from noveltyinvestigator.schema import NI_SCHEMA, NIOutput, to_record_fields


def test_model_schema_is_flat_except_closest_work_list():
    props = NI_SCHEMA["properties"]
    nested = [k for k, v in props.items() if v.get("type") == "object" or "$ref" in v]
    assert nested == [] and props["closest_work"]["type"] == "array"
    assert "minimum" not in props["confidence"] and "maximum" not in props["confidence"]


def test_record_fields_in_user_format():
    rec = to_record_fields(NIOutput.model_validate(ni_output()))
    assert rec["novelty"] == {"status": "partially_solved"}
    assert rec["checks"]["already_solved"] == {"answer": "partially", "reasoning": "AlphaFold solves most of it", "evidence": [1]}
    assert rec["checks"]["obvious_baseline"]["baseline"] == "run AlphaFold2"
    assert rec["closest_work"][0]["kind"] == "paper" and rec["confidence"] == 0.8


def test_confidence_must_be_a_probability():
    with pytest.raises(ValidationError):
        NIOutput.model_validate(ni_output(confidence=1.4))
