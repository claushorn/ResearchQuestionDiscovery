import re
import unicodedata

_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).translate(_QUOTES))
    return re.sub(r" ([.,;:!?)\]])", r"\1", s).strip()  # html_to_text puts inline tags on own lines


def quote_in_text(quote: str, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(text)
