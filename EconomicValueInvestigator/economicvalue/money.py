"""Parse monetary amounts as stated in payment signals and evidence ("$1.5M", "nearly £50m",
"$212,000 — $339,000 USD", "Award ceiling: 250,000"). No amount is ever invented: a bare number counts only
if it has thousands separators or a magnitude suffix, and a currency is only assigned when stated or when the
caller passes an explicit per-source default."""
import re
from dataclasses import dataclass

_SYMBOL = {"$": "USD", "£": "GBP", "€": "EUR"}
_CODES = ("USD", "GBP", "EUR")
_SCALE = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_AMOUNT = re.compile(
    r"(?P<pre>[$£€]|\b(?:USD|GBP|EUR)\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<suf>k|mn|m|million|bn|b|billion)\b)?"
    r"(?:\s?(?P<post>USD|GBP|EUR)\b)?", re.IGNORECASE)
_RANGE_SEP = re.compile(r"^\s*(?:—|–|-|to)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Money:
    low: float
    high: float
    currency: str | None
    text: str


def _one(m: re.Match) -> tuple[float, str | None, bool] | None:
    pre, num, suf, post = m.group("pre"), m.group("num"), m.group("suf"), m.group("post")
    currency = _SYMBOL.get(pre.strip()) if pre and pre.strip() in _SYMBOL else (pre.strip().upper() if pre else None)
    currency = currency or (post.upper() if post else None)
    if not (currency or suf or "," in num):
        return None  # a bare number (year, count, date part) is not money
    value = float(num.replace(",", "")) * (_SCALE[suf.lower()] if suf else 1)
    return value, currency, bool(suf or "," in num or currency)


def parse_amounts(text: str, default_currency: str | None = None) -> list[Money]:
    found = [(m, _one(m)) for m in _AMOUNT.finditer(text or "")]
    found = [(m, v) for m, v in found if v is not None]
    out: list[Money] = []
    i = 0
    while i < len(found):
        m, (value, currency, _) = found[i]
        if i + 1 < len(found):
            m2, (value2, currency2, _) = found[i + 1]
            if _RANGE_SEP.match(text[m.end():m2.start()]):  # "$212,000 — $339,000 USD"
                cur = currency or currency2 or default_currency
                out.append(Money(min(value, value2), max(value, value2), cur, text[m.start():m2.end()].strip()))
                i += 2
                continue
        out.append(Money(value, value, currency or default_currency, m.group(0).strip()))
        i += 1
    return out


def to_usd(m: Money, rates: dict[str, float]) -> tuple[float, float] | None:
    """USD range using the configured fixed rates; None when the currency is unknown or has no rate."""
    if m.currency is None or m.currency not in rates:
        return None
    return m.low * rates[m.currency], m.high * rates[m.currency]
