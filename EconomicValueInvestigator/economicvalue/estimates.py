"""Code-side rules that keep invented amounts out of assessments (spec §5.4).

An estimate row survives only with a basis: a `source` or `analogous_company` whose evidence page was fetched,
whose quote was found on it, and whose quote CONTAINS the row's figures (currency-consistent for money,
percentages for shares); or a labelled `explicit_assumption`. Units are validated so a free-text unit cannot
rescale a figure. Everything else becomes "unknown" and is listed in warnings. Potential value is computed here,
never by the model."""
import math
import re

from economicvalue.money import figures, parse_amounts
from economicvalue.schema import TEXT_FIELDS, EstimateRow, EVOutput

MODELS = {  # potential value (USD/year) = product of the factors; computed here, never by the model
    "incident": ("affected_units", "frequency_per_year", "cost_per_occurrence", "addressable_share"),
    "market": ("buyer_count", "annual_spend_per_buyer", "addressable_share"),
}
FACTORS = tuple(dict.fromkeys(q for qs in MODELS.values() for q in qs))
_MONEY = ("cost_per_occurrence", "annual_spend_per_buyer", "current_cost", "failure_cost")
_COUNTS = ("affected_units", "buyer_count")
_MONEY_UNIT = re.compile(r"([A-Za-z]{3})\s*(?:/\s*(\w+)|\s+per\s+(\w+))?")
_YEAR = ("year", "yr", "annum")
_TIME = _YEAR + ("month", "week", "day", "quarter", "hour")
_SCALE_WORD = re.compile(r"\b(thousands?|millions?|billions?|k|m|mn|bn)\b", re.IGNORECASE)
_RANK = {"supported": 2, "assumption_only": 1}
UNKNOWN = "unknown"


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.005 * max(abs(b), 1e-9)


def _in_quote(value: float, quote: str, currency: str | None) -> bool:
    """currency: an ISO code for money, '%' for shares (a percentage or a plain fraction), None for counts."""
    for fig, cur in figures(quote):
        if currency == "%" and ((cur == "%" and _close(value, fig)) or (cur is None and 0 <= fig <= 1 and _close(value, fig))):
            return True
        if currency not in ("%", None) and cur == currency and _close(value, fig):
            return True
        if currency is None and cur is None and _close(value, fig):
            return True
    return False


def _money_unit(unit: str, rates: dict[str, float]) -> tuple[str, float, str, str | None] | None:
    m = _MONEY_UNIT.fullmatch(unit.strip())
    if not m or m.group(1).upper() not in rates:
        return None
    period = (m.group(2) or m.group(3) or "").lower() or None
    code = m.group(1).upper()
    return code, rates[code], "USD" + (f"/{period}" if period else ""), period


def _check(row: EstimateRow, out: EVOutput, verification: list[str], rates: dict[str, float]):
    """Returns (low, high, unit, basis_entry, cited) or raises ValueError with the rejection reason."""
    vals = [v for v in (row.low, row.high) if v is not None]
    if not vals:
        raise ValueError("no value")
    if not all(math.isfinite(v) and v >= 0 for v in vals):
        raise ValueError(f"impossible value {vals}")
    low, high = min(vals), max(vals)
    unit, currency, rate = row.unit, None, 1.0
    if row.quantity in _MONEY:
        mu = _money_unit(row.unit, rates)
        if mu is None:
            raise ValueError(f"unit {row.unit!r} is not a currency with a configured rate")
        currency, rate, unit, period = mu
        if row.quantity == "cost_per_occurrence" and period in _TIME:
            raise ValueError(f"cost_per_occurrence must be per occurrence, not {row.unit!r}")
        if row.quantity == "annual_spend_per_buyer" and period not in _YEAR:
            raise ValueError(f"annual_spend_per_buyer must be per year, not {row.unit!r}")
    elif row.quantity == "addressable_share":
        if row.unit.strip().lower() not in ("share", "fraction", "ratio"):
            raise ValueError(f"addressable_share unit must be share/fraction, not {row.unit!r}")
        if not 0 <= low <= high <= 1:
            raise ValueError(f"share {low}..{high} outside [0, 1]")
        currency = "%"
    elif row.quantity in _COUNTS and _SCALE_WORD.search(row.unit):
        raise ValueError(f"unit {row.unit!r} rescales the count; state the number itself")
    elif row.quantity == "frequency_per_year":
        u = row.unit.lower()
        if not any(y in u for y in ("year", "annum", "annual")) or any(t in u for t in _TIME[3:]):
            raise ValueError(f"frequency_per_year unit must be per year, not {row.unit!r}")
    if row.basis == "explicit_assumption":
        if not row.assumption.strip():
            raise ValueError("explicit_assumption without the assumption stated")
        entry, cited = {"type": "explicit_assumption", "assumption": row.assumption}, False
    else:
        if not 1 <= row.evidence <= len(out.evidence):
            raise ValueError(f"cites evidence {row.evidence}, which does not exist")
        ev = out.evidence[row.evidence - 1]
        if verification[row.evidence - 1] != "verified":
            raise ValueError(f"evidence {row.evidence} is {verification[row.evidence - 1]}")
        if row.basis == "analogous_company" and not ev.company.strip():
            raise ValueError(f"analogous_company basis but evidence {row.evidence} names no company")
        for v in {low, high}:
            if not _in_quote(v, ev.quote, currency):
                raise ValueError(f"figure {v:g} {row.unit} not in evidence {row.evidence}'s quote")
        entry = {"type": row.basis, **({"company": ev.company} if row.basis == "analogous_company" else {}),
                 "url": ev.url, "quote": ev.quote, "verification": "verified"}
        cited = True
    return low * rate, high * rate, unit, entry, cited


def _amount_supported(m, quotes: list[str]) -> bool:
    return any(_in_quote(m.low, q, m.currency) and _in_quote(m.high, q, m.currency) for q in quotes)


def build(out: EVOutput, verification: list[str], rates: dict[str, float]) -> dict:
    warnings = {"rejected_estimates": [], "unsupported_amounts": [], "unverified_wtp": []}
    grouped: dict[str, list] = {}
    for row in out.estimates:
        label = f"{row.quantity} {row.low}..{row.high} {row.unit}"
        try:
            checked = _check(row, out, verification, rates)
        except ValueError as e:
            warnings["rejected_estimates"].append(f"{label}: {e}")
            continue
        rows = grouped.setdefault(row.quantity, [])
        if rows and rows[0][2] != checked[2]:  # one unit per quantity: never relabel a per-month figure per-year
            warnings["rejected_estimates"].append(f"{label}: unit {checked[2]} differs from {rows[0][2]}")
            continue
        rows.append(checked)

    def estimate(quantity: str):
        rows = grouped.get(quantity)
        if not rows:
            return UNKNOWN
        return {"low": min(r[0] for r in rows), "high": max(r[1] for r in rows), "unit": rows[0][2],
                "status": "supported" if any(r[4] for r in rows) else "assumption_only",
                "basis": [r[3] for r in rows]}

    factors = {q: estimate(q) for q in FACTORS}

    def model(name: str):
        fs = [factors[q] for q in MODELS[name]]
        if any(f == UNKNOWN for f in fs):
            return UNKNOWN
        low = high = 1.0
        for f in fs:
            low, high = low * f["low"], high * f["high"]
        return {"low": low, "high": high, "unit": "USD/year",
                "status": min((f["status"] for f in fs), key=_RANK.get),
                "computed_from": " × ".join(MODELS[name]), "basis": [b for f in fs for b in f["basis"]]}

    models = {name: model(name) for name in MODELS}
    known = {n: m for n, m in models.items() if m != UNKNOWN}
    if not known:
        potential = UNKNOWN
    elif len(known) == 1 or len({_RANK[m["status"]] for m in known.values()}) > 1:
        name, best = max(known.items(), key=lambda kv: _RANK[kv[1]["status"]])  # stronger support wins
        potential = {**best, "model": name}
    else:  # equal support: report the range spanning both rather than picking one
        ms = list(known.values())
        potential = {"low": min(m["low"] for m in ms), "high": max(m["high"] for m in ms), "unit": "USD/year",
                     "status": ms[0]["status"], "computed_from": " | ".join(m["computed_from"] for m in ms),
                     "basis": [b for m in ms for b in m["basis"]], "model": "both"}

    verified_quotes = [e.quote for e, v in zip(out.evidence, verification) if v == "verified"]
    for name in TEXT_FIELDS:
        for m in parse_amounts(getattr(out, name)):
            if (m.currency or m.scaled) and not _amount_supported(m, verified_quotes):
                warnings["unsupported_amounts"].append(f"{name}: {m.text}")

    wtp = []
    for s in out.willingness_to_pay:
        if not (1 <= s.evidence <= len(out.evidence) and verification[s.evidence - 1] == "verified"):
            warnings["unverified_wtp"].append(f"{s.signal} (evidence {s.evidence} not verified)")
            continue
        ev = out.evidence[s.evidence - 1]
        missing = [m.text for m in parse_amounts(s.signal) if (m.currency or m.scaled) and not _amount_supported(m, [ev.quote])]
        if missing:
            warnings["unverified_wtp"].append(f"{s.signal} (amount {', '.join(missing)} not in evidence {s.evidence}'s quote)")
            continue
        wtp.append({"signal": s.signal, "url": ev.url, "quote": ev.quote})
    return {"factors": factors, "current_cost": estimate("current_cost"), "failure_cost": estimate("failure_cost"),
            "potential_value": potential, "potential_value_models": models, "willingness_to_pay": wtp,
            "warnings": warnings}
