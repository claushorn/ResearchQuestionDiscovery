"""The user's hard requirement: the agent cannot get an amount into a record without a basis that actually
contains it. Each case is a probe from the final review (2026-09-30), reproduced as a regression test."""
import pytest

from ev_testing import FACTORS, ev_output, row
from economicvalue.estimates import build
from economicvalue.schema import EVOutput

RATES = {"USD": 1.0, "GBP": 1.25, "EUR": 1.1}


def ev(quote1="2,000 companies deploy agents in production", quote2="incidents cost us $40,000 each, the company said",
       company2="Acme"):
    return [{"title": "Survey", "url": "https://e.example/1", "kind": "statistic", "company": "", "quote": quote1},
            {"title": "Acme 10-K", "url": "https://e.example/2", "kind": "filing", "company": company2, "quote": quote2}]


def b(estimates, evidence=None, verification=("verified", "verified"), **over):
    return build(EVOutput.model_validate(ev_output(estimates=estimates, evidence=evidence or ev(), **over)),
                 list(verification), RATES)


def rejected(r, text):
    return any(text in w for w in r["warnings"]["rejected_estimates"])


# Critical 1: the cited quote must contain the row's figure
def test_A_figure_absent_from_cited_quote_is_rejected():
    r = b([row("current_cost", 7_500_000, 12_000_000, "USD/year", evidence=1)])
    assert r["current_cost"] == "unknown" and rejected(r, "not in evidence 1")


def test_B_non_monetary_quote_cannot_support_a_cost():
    r = b(FACTORS[:2] + [row("cost_per_occurrence", 999_999, 999_999, "USD", basis="analogous_company", evidence=2)] + FACTORS[3:])
    assert r["potential_value"] == "unknown"


def test_figure_present_in_quote_is_supported():
    r = b([row("cost_per_occurrence", 40_000, 40_000, "USD", basis="analogous_company", evidence=2)])
    assert r["factors"]["cost_per_occurrence"]["status"] == "supported"


def test_quote_currency_must_match_row_currency():
    r = b([row("cost_per_occurrence", 40_000, 40_000, "GBP", basis="analogous_company", evidence=2)])
    assert r["factors"]["cost_per_occurrence"] == "unknown" and rejected(r, "not in evidence 2")


def test_range_row_needs_both_ends_in_the_quote():
    r = b([row("cost_per_occurrence", 40_000, 400_000, "USD", basis="analogous_company", evidence=2)])
    assert r["factors"]["cost_per_occurrence"] == "unknown"


def test_share_supported_by_a_percentage_in_the_quote():
    r = b([row("addressable_share", 0.13, 0.13, "share", evidence=1)],
          evidence=ev(quote1="13% of surveyed organizations have experienced an attack"))
    assert r["factors"]["addressable_share"]["status"] == "supported"


def test_count_supported_by_bare_number_in_the_quote():
    r = b([row("buyer_count", 24, 24, "vendors", evidence=1)], evidence=ev(quote1="a market of 24 specialist vendors today"))
    assert r["factors"]["buyer_count"]["status"] == "supported"


# Critical 2: willingness-to-pay signal text
def test_F_wtp_signal_amount_must_be_in_its_quote():
    r = b([], willingness_to_pay=[{"signal": "Acme budgets $50M/year for this tooling", "evidence": 1},
                                  {"signal": "Acme pays $40,000 per incident", "evidence": 2}])
    assert [w["signal"] for w in r["willingness_to_pay"]] == ["Acme pays $40,000 per incident"]
    assert "not in evidence 1" in r["warnings"]["unverified_wtp"][0]


# Important 3: amount guard phrasings and currency
@pytest.mark.parametrize("text", ["costs 40 million dollars a year", "about $ 40M annually", "a 40M loss",
                                  "$2,000 per seat", "£40,000 per incident"])
def test_G_guard_flags_amounts_not_in_verified_quotes(text):
    r = b([], pain_reasoning=text)
    assert r["warnings"]["unsupported_amounts"], text


# Important 4: units cannot silently rescale the result
@pytest.mark.parametrize("quantity, unit", [("affected_units", "thousand companies"), ("buyer_count", "million users"),
                                            ("frequency_per_year", "per month"), ("addressable_share", "%")])
def test_E_rescaling_units_rejected(quantity, unit):
    r = b([row(quantity, 1, 1, unit, basis="explicit_assumption", evidence=0, assumption="x")])
    assert r["factors"][quantity] == "unknown" and rejected(r, unit)


# Important 5: one unit per quantity
def test_D_mixed_periods_are_not_merged():
    r = b([row("current_cost", 100_000, 100_000, "USD/year", basis="explicit_assumption", evidence=0, assumption="a"),
           row("current_cost", 10_000, 10_000, "USD/month", basis="explicit_assumption", evidence=0, assumption="b")])
    assert r["current_cost"]["low"] == 100_000 and rejected(r, "differs")


# Important 6: impossible values
@pytest.mark.parametrize("low, high", [(-5000, -100), (float("nan"), 1), (1, float("inf"))])
def test_C_negative_and_non_finite_values_rejected(low, high):
    r = b([row("current_cost", low, high, "USD/year", basis="explicit_assumption", evidence=0, assumption="a")])
    assert r["current_cost"] == "unknown"


# Important 7: natural per-occurrence units are accepted, time periods are not
@pytest.mark.parametrize("unit, ok", [("USD/incident", True), ("USD per occurrence", True), ("USD/event", True),
                                      ("USD/year", False), ("USD/month", False)])
def test_H_cost_per_occurrence_units(unit, ok):
    r = b([row("cost_per_occurrence", 40_000, 40_000, unit, basis="analogous_company", evidence=2)])
    assert (r["factors"]["cost_per_occurrence"] != "unknown") == ok
