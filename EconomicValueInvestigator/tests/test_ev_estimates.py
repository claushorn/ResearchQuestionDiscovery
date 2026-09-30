import pytest
from pydantic import ValidationError

from ev_testing import FACTORS, ev_output, row
from economicvalue.estimates import build
from economicvalue.schema import EV_SCHEMA, EVOutput

RATES = {"USD": 1.0, "EUR": 1.1}
OK = ["verified", "verified"]


def b(estimates=None, verification=OK, **over):
    return build(EVOutput.model_validate(ev_output(estimates=estimates, **over)), verification, RATES)


def test_schema_is_flat():
    props = EV_SCHEMA["properties"]
    assert not [k for k, v in props.items() if v.get("type") == "object" or "$ref" in v]
    assert {props[k]["type"] for k in ("evidence", "estimates", "willingness_to_pay")} == {"array"}
    with pytest.raises(ValidationError):
        EVOutput.model_validate(ev_output(pain_score=11))


def test_verified_source_row_is_supported():
    r = b([row("current_cost", 100, 200, "USD/year")])
    cc = r["current_cost"]
    assert (cc["low"], cc["high"], cc["unit"], cc["status"]) == (100, 200, "USD/year", "supported")
    assert cc["basis"] == [{"type": "source", "url": "https://e.example/1", "quote": "2,000 companies deploy agents",
                            "verification": "verified"}]


def test_invalid_evidence_number_rejects_and_value_becomes_unknown():
    r = b([row("current_cost", 100, 200, "USD/year", evidence=7)])
    assert r["current_cost"] == "unknown" and "evidence 7" in r["warnings"]["rejected_estimates"][0]


def test_unverified_quote_rejects():
    r = b([row("current_cost", 100, 200, "USD/year")], verification=["quote_not_found", "verified"])
    assert r["current_cost"] == "unknown" and "quote_not_found" in r["warnings"]["rejected_estimates"][0]


def test_assumption_only_is_kept_and_labelled():
    r = b([row("failure_cost", 5000, 9000, "USD", basis="explicit_assumption", evidence=0, assumption="one outage")])
    assert r["failure_cost"]["status"] == "assumption_only"
    assert r["failure_cost"]["basis"] == [{"type": "explicit_assumption", "assumption": "one outage"}]


def test_assumption_row_without_text_rejected():
    assert b([row("failure_cost", 1, 2, "USD", basis="explicit_assumption", evidence=0)])["failure_cost"] == "unknown"


def test_mixed_rows_supported_with_min_max():
    r = b([row("current_cost", 100, 200, "USD/year"),
           row("current_cost", 50, 300, "USD/year", basis="explicit_assumption", evidence=0, assumption="a")])
    assert (r["current_cost"]["low"], r["current_cost"]["high"], r["current_cost"]["status"]) == (50, 300, "supported")


def test_analogous_company_needs_named_company():
    r = b([row("current_cost", 1, 2, "USD", basis="analogous_company", evidence=1)])  # evidence 1 has no company
    assert r["current_cost"] == "unknown" and "company" in r["warnings"]["rejected_estimates"][0]


def test_currency_converted_and_non_money_unit_rejected():
    r = b([row("current_cost", 100, 100, "EUR/year"), row("failure_cost", 10, 10, "person-hours")])
    assert r["current_cost"]["low"] == pytest.approx(110) and r["current_cost"]["unit"] == "USD/year"
    assert r["failure_cost"] == "unknown" and "person-hours" in r["warnings"]["rejected_estimates"][0]


def test_share_outside_unit_interval_rejected():
    assert b([row("addressable_share", 0.2, 1.5, "share")])["factors"]["addressable_share"] == "unknown"


def test_potential_value_computed_by_code_with_weakest_status():
    r = b(FACTORS)
    pv = r["potential_value"]
    assert pv["low"] == pytest.approx(1000 * 2 * 40000 * 0.05) and pv["high"] == pytest.approx(2000 * 4 * 40000 * 0.1)
    assert pv["unit"] == "USD/year" and pv["status"] == "assumption_only" and len(pv["basis"]) == 4


def test_unknown_factor_makes_potential_unknown():
    assert b(FACTORS[:3])["potential_value"] == "unknown"


def test_per_period_cost_per_occurrence_rejected():
    rows = FACTORS[:2] + [row("cost_per_occurrence", 1, 1, "USD/year", basis="analogous_company", evidence=2)] + FACTORS[3:]
    assert b(rows)["potential_value"] == "unknown"


def test_amount_guard_flags_amounts_not_in_verified_quotes():
    r = b([], how_expensive="each incident costs $40,000; the market is $40M")
    assert r["warnings"]["unsupported_amounts"] == ["how_expensive: $40M"]


def test_amount_in_unverified_quote_is_unsupported():
    r = b([], verification=["verified", "quote_not_found"], how_expensive="each incident costs $40,000")
    assert r["warnings"]["unsupported_amounts"] == ["how_expensive: $40,000"]


def test_willingness_to_pay_keeps_only_verified_evidence():
    r = b([], willingness_to_pay=[{"signal": "Acme pays for tooling", "evidence": 2},
                                  {"signal": "rumoured budget", "evidence": 5}])
    assert r["willingness_to_pay"] == [{"signal": "Acme pays for tooling", "url": "https://e.example/2",
                                        "quote": "incidents cost us $40,000 each"}]
    assert r["warnings"]["unverified_wtp"] == ["rumoured budget (evidence 5)"]
