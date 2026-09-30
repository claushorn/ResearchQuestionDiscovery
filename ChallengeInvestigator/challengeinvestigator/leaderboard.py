"""Scrape a finished challenge's final leaderboard (deterministic; the page is the source). Layouts measured
2026-09-30: AIcrowd /leaderboards (primary column th.score-title, baseline rows title="Baseline", default page = the
last round's main leaderboard) and DrivenData leaderboard_partial (rows data-rank, "Best private <metric>" column)."""
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from rqd.errors import ItemExtractionError, SourceFetchError
from rqd.http import Fetcher

_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")


class LeaderboardError(ItemExtractionError):
    """The leaderboard could not be read (fetch failed or the layout is not the measured one): that challenge fails."""


class NoLeaderboard(Exception):
    """The challenge has no leaderboard page (e.g. a judged competition)."""


@dataclass(frozen=True)
class Leaderboard:
    url: str
    label: str                            # the round / track shown, e.g. "Round 2 · Overall"
    metric: str                           # the primary score column's name
    ranked: list[tuple[str, float]]       # (team, score), rank 1 first
    baselines: list[tuple[str, float]]    # the organisers' baseline rows, if the page lists them


def _text(node: Node) -> str:
    return re.sub(r"\s+", " ", node.text(separator=" ")).strip()


def _cells(tr: Node) -> list[Node]:
    return [c for c in tr.iter() if c.tag in ("td", "th")]


def _score(cell: Node) -> float | None:
    t = _text(cell)
    return float(t) if _NUMBER.match(t) else None


def _table(html: str, url: str) -> Node:
    table = HTMLParser(html).css_first("table")
    if table is None:
        raise LeaderboardError(f"{url}: no leaderboard table (layout changed?)")
    return table


def parse_aicrowd(html: str, url: str) -> Leaderboard:
    table = _table(html, url)
    rows = table.css("tr")
    head = [_text(c) for c in _cells(rows[0])]
    titles = [i for i, c in enumerate(_cells(rows[0])) if "score-title" in (c.attributes.get("class") or "").split()]
    if not titles or "#" not in head or "Participants" not in head:
        raise LeaderboardError(f"{url}: no primary score column (th.score-title, #, Participants) (layout changed?)")
    col, rank, name = titles[0], head.index("#"), head.index("Participants")
    ranked, baselines = [], []
    for tr in rows[1:]:
        cells = _cells(tr)
        if len(cells) <= col or (score := _score(cells[col])) is None:
            continue
        if tr.css_first('[title="Baseline"]') is not None:
            baselines.append((re.sub(r"^Baseline\s+", "", _text(cells[name])), score))
        elif _text(cells[rank]).isdigit():
            ranked.append((_text(cells[name]), score))
    if not ranked:
        raise LeaderboardError(f"{url}: no ranked rows with a score")
    active = [_text(a) for a in HTMLParser(html).css("a.active")]
    return Leaderboard(url, " · ".join(a for a in active if a), head[col], ranked, baselines)


def parse_drivendata(html: str, url: str) -> Leaderboard:
    table = _table(html, url)
    rows = table.css("tr")
    head = _cells(rows[0])
    cols = [i for i, c in enumerate(head) if "Best private" in _text(c)]
    if not cols:
        raise LeaderboardError(f"{url}: no 'Best private' score column: not a final private leaderboard")
    metric_node = head[cols[0]].css_first('[title^="Metric:"]')
    metric = metric_node.attributes["title"].removeprefix("Metric:").strip() if metric_node else _text(head[cols[0]])
    ranked = []
    for tr in rows[1:]:
        if "data-rank" not in tr.attributes:
            continue
        cells = _cells(tr)
        team = cells[2].css_first(".fw-bold") if len(cells) > 2 else None
        if team is not None and len(cells) > cols[0] and (score := _score(cells[cols[0]])) is not None:
            ranked.append((_text(team), score))
    if not ranked:
        raise LeaderboardError(f"{url}: no ranked rows with a score")
    return Leaderboard(url, "private leaderboard", metric, ranked, [])


def _get(fetcher: Fetcher, url: str) -> str:
    try:
        return fetcher.get(url).text
    except SourceFetchError as e:
        if e.status == 404:
            raise NoLeaderboard(f"no leaderboard page ({url}: HTTP 404)") from e
        raise LeaderboardError(str(e)) from e


def fetch_leaderboard(fetcher: Fetcher, kind: str, challenge_url: str) -> Leaderboard:
    if kind == "aicrowd":
        url = challenge_url.rstrip("/") + "/leaderboards"
        return parse_aicrowd(_get(fetcher, url), url)
    url = challenge_url.rstrip("/") + "/leaderboard/"
    partial = re.search(r'hx-get="([^"]*leaderboard_partial[^"]*)"', _get(fetcher, url))
    if partial is None:
        raise LeaderboardError(f"{url}: no leaderboard_partial request found (layout changed?)")
    try:
        html = fetcher.get(urljoin(url, partial.group(1).replace("&amp;", "&"))).text
    except SourceFetchError as e:
        raise LeaderboardError(str(e)) from e
    lb = parse_drivendata(html, url)
    return Leaderboard(url, lb.label, lb.metric, lb.ranked, lb.baselines)
