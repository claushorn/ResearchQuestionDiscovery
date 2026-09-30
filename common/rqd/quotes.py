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


_NUM = re.compile(r"\d+(?:\.\d+)?(?:[eE]-?\d+)?")
_WORD = re.compile(r"[a-z][a-z0-9_\-]{2,}")


def _numbers(s: str) -> list[float]:
    return [float(n) for n in _NUM.findall(s)]


def row_in_html(quote: str, html: str) -> bool:
    """A leaderboard quote such as "pranav_devarinti 19.369" or "ACPL: 19.369 | Win Rate: 97.0%": every number in
    the quote appears (numerically equal) in ONE table row, and at least one quote word appears in that row or in
    the table's header row. Rows are real <tr> elements, so a neighbouring row's score cannot be attributed."""
    from selectolax.parser import HTMLParser

    q = _norm(quote)
    nums, words = _numbers(q), set(_WORD.findall(q))
    if not nums or not words:
        return False
    for table in HTMLParser(html).css("table"):
        rows = [_norm(r.text(separator=" ")) for r in table.css("tr")]
        header = set(_WORD.findall(rows[0])) if rows else set()
        for row in rows:
            row_nums = _numbers(row)
            if all(any(abs(n - r) <= 1e-9 * max(abs(r), 1.0) for r in row_nums) for n in nums) and \
                    (words & (set(_WORD.findall(row)) | header)):
                return True
    return False
