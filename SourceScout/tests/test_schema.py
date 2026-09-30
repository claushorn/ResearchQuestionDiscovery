import pytest
from pydantic import BaseModel, Field, ValidationError

from sourcescout.schema import EXTRACTION_SCHEMA, ExtractionResult, api_schema, length_violations

FORBIDDEN = {"maxLength", "minLength", "maxItems", "minItems", "title", "default"}


def walk(node):
    if isinstance(node, dict):
        yield node
        for k, v in node.items():
            if k in ("properties", "$defs"):
                for sub in v.values():
                    yield from walk(sub)
            else:
                yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def test_api_schema_is_structured_output_compatible():
    for node in walk(EXTRACTION_SCHEMA):
        assert not (FORBIDDEN & node.keys()), node
        if node.get("type") == "object":
            assert node["additionalProperties"] is False


def test_sanitizer_keeps_property_named_title():
    class M(BaseModel):
        title: str = Field(default="x", max_length=5)
    s = api_schema(M)
    assert "title" in s["properties"] and s["additionalProperties"] is False
    assert "default" not in s["properties"]["title"]


def cand(**kw):
    base = {"statement": "Forecast grid load under extreme weather.", "why_interesting": "Utility says outages cost millions.",
            "explicit_unsolved_signal": {"present": True, "evidence": "remains an open challenge"},
            "payment_signal": {"type": "grant", "stated": "$1.5M", "evidence": "up to $1.5M", "deadline": None},
            "technical_area": ["forecasting"], "entities": {"organizations": ["DOE"], "researchers": []},
            "referenced_urls": []}
    return base | kw


def test_max_three_candidates():
    ExtractionResult.model_validate({"candidates": [cand()] * 3})
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"candidates": [cand()] * 4})


def test_length_violations():
    c = ExtractionResult.model_validate({"candidates": [cand(statement="word " * 61)]}).candidates[0]
    assert length_violations(c) == ["statement"]
