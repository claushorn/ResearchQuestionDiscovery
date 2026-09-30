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


_NUM = r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_WORD = r"[a-z][a-z0-9_\-]+"
_TOK = re.compile(f"(?P<num>{_NUM})|(?P<word>{_WORD})")


def _words(s: str) -> set[str]:
    return set(re.findall(_WORD, s))


def _has_number(n: float, cell: str) -> bool:
    return any(abs(n - float(c)) <= 1e-9 * max(abs(float(c)), 1.0) for c in re.findall(_NUM, cell))


def _own_rows(table) -> list[list[str]]:
    """The table's rows as cell texts; rows of a nested table belong to that table, not this one."""
    rows = []
    for tr in table.css("tr"):
        parent = tr.parent
        while parent is not None and parent.tag != "table":
            parent = parent.parent
        if parent is not None and parent.mem_id == table.mem_id:
            rows.append([_norm(c.text(separator=" ")) for c in tr.iter() if c.tag in ("td", "th")])
    return rows


def _row_matches(toks: list[tuple[str, str]], header: list[set[str]], cells: list[str]) -> bool:
    head = set().union(*header)
    row = set().union(*map(_words, cells))
    words = {v for kind, v in toks if kind == "word"}
    if not words <= row | head or not (words - head) & row:
        return False  # every word is on the row or in the header, and one identifies the row (the team)
    segment: set[str] = set()
    for kind, v in toks:
        if kind == "word":
            segment |= {v} & head
            continue
        # the number sits in the column its preceding header word(s) name: "alpha_team Score 0.768"
        cols = [i for i, h in enumerate(header) if segment and segment <= h and i < len(cells)]
        if not any(_has_number(float(v), cells[i]) for i in cols):
            return False
        segment = set()
    return True


def row_in_html(quote: str, html: str) -> bool:
    """A leaderboard quote "<team> <column heading> <cell> [<column heading> <cell> ...]", e.g.
    "pranav_devarinti ACPL 19.369": one row of a table contains the team word(s), and each number is in the cell of
    the column named by the heading word(s) before it (so a rank, entries or date column never backs a score, and a
    neighbouring row's score is never attributed). Every quote word must be on that row or in the header."""
    from selectolax.parser import HTMLParser

    toks = [(m.lastgroup, m.group()) for m in _TOK.finditer(_norm(quote))]
    if not any(kind == "num" for kind, _ in toks):
        return False
    for table in HTMLParser(html).css("table"):
        rows = _own_rows(table)
        if len(rows) < 2:
            continue
        header = [_words(h) for h in rows[0]]
        if any(_row_matches(toks, header, cells) for cells in rows[1:]):
            return True
    return False
