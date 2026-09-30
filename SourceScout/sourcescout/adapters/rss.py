import feedparser

from sourcescout.adapters.base import IsKnown, RawItem, item_failed
from rqd.errors import SourceFetchError
from rqd.http import Fetcher, html_to_text
from sourcescout.registry import Source


def fetch(source: Source, http: Fetcher, is_known: IsKnown,
          item_errors: list[str] | None = None) -> list[RawItem]:
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
            try:
                text, links = html_to_text(http.get(url).text, url)
            except SourceFetchError as e:
                item_failed(item_errors, url, e)
                continue
        else:
            body = entry["content"][0].get("value", "") if entry.get("content") else entry.get("summary", "")
            text, links = html_to_text(body, url)
        items.append(RawItem(source.id, url, entry.get("title") or "", entry.get("published") or entry.get("updated"),
                             text, tuple(links)))
    return items
