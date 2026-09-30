import feedparser

from sourcescout.adapters.base import IsKnown, RawItem
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher, html_to_text
from sourcescout.registry import Source


def fetch(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    resp = http.get(source.url)
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise SourceFetchError(f"{source.url}: not a parseable feed ({feed.get('bozo_exception')})")
    fetch_full = bool(source.params.get("fetch_full", False))
    items = []
    for entry in feed.entries[: int(source.params.get("max_items", 30))]:
        url = entry.get("link")
        if not url:
            continue
        if fetch_full:
            if is_known(url):
                continue
            text, links = html_to_text(http.get(url).text, url)
        else:
            body = entry["content"][0].get("value", "") if entry.get("content") else entry.get("summary", "")
            text, links = html_to_text(body, url)
        items.append(RawItem(source.id, url, entry.get("title", ""), entry.get("published") or entry.get("updated"),
                             text, tuple(links)))
    return items
