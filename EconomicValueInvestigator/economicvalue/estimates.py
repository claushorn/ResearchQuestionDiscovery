"""Code-side rules that keep invented amounts out of assessments (spec §5.4).

An estimate survives only with a basis: a `source` or `analogous_company` whose evidence quote was verified by
fetching the page, or a labelled `explicit_assumption`. Everything else becomes "unknown" and is listed in
warnings. potential_value is computed here, never by the model."""
import re

from economicvalue.money import parse_amounts
from economicvalue.schema import TEXT_FIELDS, EstimateRow, EVOutput

FACTORS = ("affected_units", "frequency_per_year", "cost_per_occurrence", "addressable_share")
_MONEY = ("cost_per_occurrence", "current_cost", "failure_cost")
_MONEY_UNIT = re.compile(r"([A-Za-z]{3})\s*(?:/\s*(\w+)|\s+per\s+(\w+))?")
UNKNOWN = "unknown"


def _money_unit(unit: str, rates: dict[str, float]) -> tuple[float, str, str | None] | None:
    m = _MONEY_UNIT.fullmatch(unit.strip())
    if not m or m.group(1).upper() not in rates:
        return None
    period = m.group(2) or m.group(3)
    return rates[m.group(1).upper()], "USD" + (f"/{period}" if period else ""), period


def _check(row: EstimateRow, out: EVOutput, verification: list[str], rates: dict[str, float]):
    """Returns (low, high, unit, basis_entry, cited) or raises ValueError with the rejection reason."""
    if row.low is None and row.high is None:
        raise ValueError("no value")
    low, high = sorted((row.low if row.low is not None else row.high, row.high if row.high is not None else row.low))
    unit = row.unit
    if row.quantity in _MONEY:
        mu = _money_unit(row.unit, rates)
        if mu is None:
            raise ValueError(f"unit {row.unit!r} is not a currency with a configured rate")
        rate, unit, period = mu
        if row.quantity == "cost_per_occurrence" and period:
            raise ValueError(f"cost_per_occurrence must be per occurrence, not {row.unit!r}")
        low, high = low * rate, high * rate
    elif row.quantity == "addressable_share" and not (0 <= low <= high <= 1):
        raise ValueError(f"share {low}..{high} outside [0, 1]")
    elif low < 0:
        raise ValueError("negative value")
    if row.basis == "explicit_assumption":
        if not row.assumption.strip():
            raise ValueError("explicit_assumption without the assumption stated")
        return low, high, unit, {"type": "explicit_assumption", "assumption": row.assumption}, False
    if not 1 <= row.evidence <= len(out.evidence):
        raise ValueError(f"cites evidence {row.evidence}, which does not exist")
    ev = out.evidence[row.evidence - 1]
    if verification[row.evidence - 1] != "verified":
        raise ValueError(f"evidence {row.evidence} is {verification[row.evidence - 1]}")
    entry = {"type": row.basis, "url": ev.url, "quote": ev.quote, "verification": "verified"}
    if row.basis == "analogous_company":
        if not ev.company.strip():
            raise ValueError(f"analogous_company basis but evidence {row.evidence} names no company")
        entry = {"type": row.basis, "company": ev.company, **{k: entry[k] for k in ("url", "quote", "verification")}}
    return low, high, unit, entry, True


def _amounts_supported_by(quotes: list[str]) -> list[tuple[float, float]]:
    return [(m.low, m.high) for q in quotes for m in parse_amounts(q)]


def _supported(value: tuple[float, float], known: list[tuple[float, float]]) -> bool:
    return any(abs(value[0] - k[0]) <= 0.005 * max(k[0], 1) and abs(value[1] - k[1]) <= 0.005 * max(k[1], 1)
               for k in known)


def build(out: EVOutput, verification: list[str], rates: dict[str, float]) -> dict:
    warnings = {"rejected_estimates": [], "unsupported_amounts": [], "unverified_wtp": []}
    grouped: dict[str, list] = {}
    for row in out.estimates:
        try:
            grouped.setdefault(row.quantity, []).append(_check(row, out, verification, rates))
        except ValueError as e:
            warnings["rejected_estimates"].append(f"{row.quantity} {row.low}..{row.high} {row.unit}: {e}")

    def estimate(quantity: str):
        rows = grouped.get(quantity)
        if not rows:
            return UNKNOWN
        return {"low": min(r[0] for r in rows), "high": max(r[1] for r in rows), "unit": rows[0][2],
                "status": "supported" if any(r[4] for r in rows) else "assumption_only",
                "basis": [r[3] for r in rows]}

    factors = {q: estimate(q) for q in FACTORS}
    if any(f == UNKNOWN for f in factors.values()):
        potential = UNKNOWN
    else:
        low = high = 1.0
        for f in factors.values():
            low, high = low * f["low"], high * f["high"]
        potential = {"low": low, "high": high, "unit": "USD/year",
                     "status": "assumption_only" if any(f["status"] == "assumption_only" for f in factors.values())
                     else "supported",
                     "computed_from": "affected_units × frequency_per_year × cost_per_occurrence × addressable_share",
                     "basis": [b for f in factors.values() for b in f["basis"]]}

    verified_quotes = [e.quote for e, v in zip(out.evidence, verification) if v == "verified"]
    known = _amounts_supported_by(verified_quotes)
    for name in TEXT_FIELDS:
        for m in parse_amounts(getattr(out, name)):
            if m.currency and not _supported((m.low, m.high), known):
                warnings["unsupported_amounts"].append(f"{name}: {m.text}")

    wtp = []
    for s in out.willingness_to_pay:
        if 1 <= s.evidence <= len(out.evidence) and verification[s.evidence - 1] == "verified":
            ev = out.evidence[s.evidence - 1]
            wtp.append({"signal": s.signal, "url": ev.url, "quote": ev.quote})
        else:
            warnings["unverified_wtp"].append(f"{s.signal} (evidence {s.evidence})")
    return {"factors": factors, "current_cost": estimate("current_cost"), "failure_cost": estimate("failure_cost"),
            "potential_value": potential, "willingness_to_pay": wtp, "warnings": warnings}
