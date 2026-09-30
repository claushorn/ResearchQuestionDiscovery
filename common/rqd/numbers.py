"""Parse monetary amounts as stated in payment signals and evidence ("$1.5M", "nearly £50m",
"$212,000 — $339,000 USD", "Award ceiling: 250,000", "10-15 million", "40 million dollars"). No amount is ever
invented: a bare number counts only if it has thousands separators or a magnitude suffix, and a currency is only
assigned when stated or when the caller passes an explicit per-source default. `figures` lists every number in a
quote (bare numbers and percentages included) so a cited estimate can be checked against its quote."""
import re
from dataclasses import dataclass

_SYMBOL = {"$": "USD", "£": "GBP", "€": "EUR"}
_WORDS = {"dollar": "USD", "dollars": "USD", "pound": "GBP", "pounds": "GBP", "euro": "EUR", "euros": "EUR"}
_SCALE = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_TOKEN = re.compile(
    r"(?P<pre>[$£€]\s?|\b(?:USD|GBP|EUR)\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3}){2,}|\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"(?![0-9]*(?:st|nd|rd|th)\b)"  # "1st place" is a rank, not a figure
    r"(?P<pct>\s?(?:%|percent\b))?"
    r"(?:\s?(?P<suf>k|mn|m|million|bn|b|billion)\b)?"
    r"(?:\s?(?P<post>USD|GBP|EUR|dollars?|pounds?|euros?)\b)?", re.IGNORECASE)
_RANGE_SEP = re.compile(r"^\s*(?:—|–|-|to)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Money:
    low: float
    high: float
    currency: str | None
    text: str
    scaled: bool = False  # had a magnitude suffix (k, m, bn ...)


@dataclass(frozen=True)
class _Tok:
    value: float        # unscaled
    scale: float
    currency: str | None
    money_like: bool    # currency, suffix or thousands separators
    percent: bool
    start: int
    end: int


def _tokens(text: str) -> list[_Tok]:
    out = []
    for m in _TOKEN.finditer(text or ""):
        pre, num, suf, post = m.group("pre"), m.group("num"), m.group("suf"), m.group("post")
        pre = pre.strip() if pre else None
        currency = _SYMBOL.get(pre) if pre in _SYMBOL else (pre.upper() if pre else None)
        if post:
            currency = currency or _WORDS.get(post.lower(), post.upper())
        grouped = "," in num or num.count(".") >= 2
        value = float(num.replace(",", "") if "," in num else (num.replace(".", "") if num.count(".") >= 2 else num))  # 3.7e-10 ok
        if suf and ("e" in num or "E" in num):
            suf = None  # "3.7e-10 M" is molar, not million: no magnitude suffix on scientific notation
        out.append(_Tok(value, _SCALE[suf.lower()] if suf else 1.0, currency, bool(currency or suf or grouped),
                        bool(m.group("pct")), m.start(), m.end()))
    return out


def parse_amounts(text: str, default_currency: str | None = None) -> list[Money]:
    toks = [t for t in _tokens(text) if not t.percent]
    out: list[Money] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if i + 1 < len(toks) and toks[i + 1].money_like and _RANGE_SEP.match(text[t.end:toks[i + 1].start]):
            u = toks[i + 1]  # "$3.5-4.5m", "10-15 million", "$212,000 — $339,000 USD"
            scale_low = t.scale if t.scale != 1.0 else u.scale
            lo, hi = t.value * scale_low, u.value * u.scale
            out.append(Money(min(lo, hi), max(lo, hi), t.currency or u.currency or default_currency,
                             text[t.start:u.end].strip(), t.scale != 1.0 or u.scale != 1.0))
            i += 2
            continue
        if t.money_like:
            out.append(Money(t.value * t.scale, t.value * t.scale, t.currency or default_currency,
                             text[t.start:t.end].strip(), t.scale != 1.0))
        i += 1
    return out


def figures(text: str) -> list[tuple[float, str | None]]:
    """Every number stated in a quote: (value, currency | '%' | None). Percentages as fractions; range ends separately."""
    out = []
    for t in _tokens(text):
        if t.percent:
            out.append((t.value / 100, "%"))
        else:
            out.append((t.value * t.scale, t.currency))
    for m in parse_amounts(text):  # ranges propagate a suffix/currency to their low end ("$3.5-4.5m")
        out += [(m.low, m.currency), (m.high, m.currency)]
    return out


def to_usd(m: Money, rates: dict[str, float]) -> tuple[float, float] | None:
    """USD range using the configured fixed rates; None when the currency is unknown or has no rate."""
    if m.currency is None or m.currency not in rates:
        return None
    return m.low * rates[m.currency], m.high * rates[m.currency]


def _close(a: float, b: float) -> bool:
    """Same number as stated (float precision only): 0.87 is not 0.871, $1.4M is not $1.5M."""
    return abs(a - b) <= 1e-9 * max(abs(b), 1.0)


def figure_in_quote(value: float, quote: str, kind: str | None) -> bool:
    """Is `value` stated in `quote`? kind: an ISO currency code for money (same currency required), '%' for
    shares (a percentage, or a plain fraction in [0, 1]), None for plain numbers (counts, scores)."""
    for fig, cur in figures(quote):
        if kind == "%" and ((cur == "%" and _close(value, fig)) or (cur is None and 0 <= fig <= 1 and _close(value, fig))):
            return True
        if kind not in ("%", None) and cur == kind and _close(value, fig):
            return True
        if kind is None and cur is None and _close(value, fig):
            return True
    return False


def stated(value: float, quote: str) -> bool:
    """A score or plain number as stated: 0.871 or 87.1 for "87.1%" (the hundredfold reading only with an explicit
    percent sign: 50 is not stated by "0.5")."""
    return any((cur is None or cur == "%") and _close(value, fig) or cur == "%" and _close(value / 100, fig)
               for fig, cur in figures(quote))


_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(\s?(?:%|percent\b))?")


def numbers_in_text(text: str) -> list[tuple[float, bool]]:
    """Decimals and percentages stated in free text (scores, gains); integers such as ranks, years or counts are
    not included. Returns (value, is_percent)."""
    out = []
    for m in _NUMBER.finditer(text or ""):
        if m.group(2) or "." in m.group(1):
            out.append((float(m.group(1)), bool(m.group(2))))
    return out
