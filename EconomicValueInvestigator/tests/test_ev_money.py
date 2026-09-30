import pytest

from economicvalue.money import parse_amounts, to_usd

RATES = {"USD": 1.0, "GBP": 1.25, "EUR": 1.1}


@pytest.mark.parametrize("text, expected", [
    ("$1.5M", [(1_500_000, 1_500_000, "USD")]),
    ("Award ceiling: 250,000", [(250_000, 250_000, None)]),
    ("nearly £50m", [(50_000_000, 50_000_000, "GBP")]),
    ("$212,000 — $339,000 USD", [(212_000, 339_000, "USD")]),
    ("$145,000 – $180,000", [(145_000, 180_000, "USD")]),
    ("USD 17,000 Prize Money", [(17_000, 17_000, "USD")]),
    ("€2 million", [(2_000_000, 2_000_000, "EUR")]),
    ("$1,000 USD (Best Designed Binder); $100 USD (Runner-up)", [(1_000, 1_000, "USD"), (100, 100, "USD")]),
    ("Estimated total funding: 1,600,000", [(1_600_000, 1_600_000, None)]),
    ("$8.5 billion market", [(8_500_000_000, 8_500_000_000, "USD")]),
    ("grant", []),
    ("deadline 2026-12-01, 3 months, 40 hours", []),
])
def test_parse_amounts(text, expected):
    assert [(m.low, m.high, m.currency) for m in parse_amounts(text)] == expected


def test_default_currency_applies_only_when_none_is_stated():
    assert [m.currency for m in parse_amounts("Award ceiling: 250,000", default_currency="USD")] == ["USD"]
    assert [m.currency for m in parse_amounts("£1m", default_currency="USD")] == ["GBP"]


def test_to_usd_uses_configured_rates_and_refuses_unknown():
    [m] = parse_amounts("£50m")
    assert to_usd(m, RATES) == (62_500_000, 62_500_000)
    assert to_usd(parse_amounts("Award ceiling: 250,000")[0], RATES) is None
    assert to_usd(parse_amounts("CHF 5,000")[0] if parse_amounts("CHF 5,000") else None, RATES) is None
