import httpx
import pytest
from pydantic import ValidationError

from ni_testing import ni_output, pdf_bytes
from noveltyinvestigator.schema import NI_SCHEMA, NIOutput, to_record_fields
from noveltyinvestigator.verify import verify_work
from rqd.http import pdf_to_text
from rqd_testing import make_fetcher

HTML = "<html><body><p>AlphaFold predicts protein structures with atomic accuracy.</p></body></html>"


def test_pdf_to_text_extracts_page_text():
    assert "three-track network" in pdf_to_text(pdf_bytes("A three-track network for structure"))


@pytest.mark.parametrize("route, quote, expected", [
    (HTML, "predicts protein structures with atomic accuracy", "verified"),
    (HTML, "a sentence the page does not contain", "quote_not_found"),
    (httpx.Response(404), "anything", "unfetchable"),
    (httpx.Response(200, content=pdf_bytes("A three-track network for structure"),
                    headers={"content-type": "application/pdf"}), "three-track network", "verified"),
])
def test_verify_work(route, quote, expected):
    f = make_fetcher({"GET https://paper.example/x": route})
    assert verify_work(f, "https://paper.example/x", quote) == expected


def test_robots_disallow_is_unfetchable():
    f = make_fetcher({"GET https://paper.example/x": HTML}, robots="User-agent: *\nDisallow: /\n")
    assert verify_work(f, "https://paper.example/x", "atomic accuracy") == "unfetchable"


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


@pytest.mark.parametrize("url", ["", "not a url", "ftp://paper.example/x"])
def test_model_supplied_non_http_url_is_unfetchable(url):
    assert verify_work(make_fetcher({}), url, "quote") == "unfetchable"


def test_unparsable_pdf_is_unfetchable():
    f = make_fetcher({"GET https://paper.example/x": httpx.Response(200, content=b"%PDF-1.4 broken",
                                                                   headers={"content-type": "application/pdf"})})
    assert verify_work(f, "https://paper.example/x", "quote") == "unfetchable"
