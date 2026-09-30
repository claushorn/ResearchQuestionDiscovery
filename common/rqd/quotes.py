import re
import unicodedata

_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_QUOTES)
    s = re.sub(r"\*\*|__|`", "", s)  # markdown emphasis: models quote a README's source, the page shows it rendered
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r" ([.,;:!?)\]])", r"\1", s).strip()  # html_to_text puts inline tags on own lines
    return s.casefold()  # a quote starting mid-sentence is often capitalised by the model (measured)


def quote_in_text(quote: str, text: str) -> bool:
    """Verbatim wording, ignoring case, typography, whitespace and the excerpt's own terminal punctuation
    (models end a mid-sentence excerpt with "." where the page continues with "," — measured)."""
    q = _norm(quote).rstrip(".,;:!?")
    if not q:
        return False
    # the quote must start and end on a word/number boundary: "$40" must not verify against "$400"
    left = r"(?<![0-9a-z])" if q[0].isalnum() else ""
    right = r"(?![0-9a-z])" if q[-1].isalnum() else ""
    return re.search(left + re.escape(q) + right, _norm(text)) is not None
