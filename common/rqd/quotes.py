import re
import unicodedata

_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).translate(_QUOTES))
    s = re.sub(r" ([.,;:!?)\]])", r"\1", s).strip()  # html_to_text puts inline tags on own lines
    return s.casefold()  # a quote starting mid-sentence is often capitalised by the model (measured)


def quote_in_text(quote: str, text: str) -> bool:
    """Verbatim wording, ignoring case, typography, whitespace and the excerpt's own terminal punctuation
    (models end a mid-sentence excerpt with "." where the page continues with "," — measured)."""
    q = _norm(quote).rstrip(".,;:!?")
    return bool(q) and q in _norm(text)
