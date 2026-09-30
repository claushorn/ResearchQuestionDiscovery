import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from sourcescout.adapters.base import IsKnown, RawItem, item_failed
from rqd.errors import SourceFetchError
from rqd.http import Fetcher, html_to_text
from sourcescout.registry import Source

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def page_item(source: Source, url: str, html: str) -> RawItem:
    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else url
    selector = source.params.get("content_selector")
    if selector:
        node = tree.css_first(selector)
        if node is None:
            raise SourceFetchError(f"content_selector {selector!r} matched nothing at {url}")
        html = node.html
    text, links = html_to_text(html, url)
    return RawItem(source.id, url, title, None, text, tuple(links))


def fetch_page(source: Source, http: Fetcher, is_known: IsKnown,
               item_errors: list[str] | None = None) -> list[RawItem]:
    resp = http.get(source.url)
    return [page_item(source, str(resp.url), resp.text)]


def fetch_list(source: Source, http: Fetcher, is_known: IsKnown,
               item_errors: list[str] | None = None) -> list[RawItem]:
    p = source.params
    resp = http.get(source.url)
    stop = re.compile(p["stop_at_heading"]) if p.get("stop_at_heading") else None
    skip = re.compile(p["skip_link_text"]) if p.get("skip_link_text") else None
    urls, finished = [], set()
    for node in HTMLParser(resp.text).root.traverse():  # document order, so sections can end the listing
        if stop and node.tag in _HEADINGS and stop.search(node.text(separator=" ")):
            break  # e.g. "Completed competitions": everything below is finished
        if node.tag != "a" or not node.css_matches(p["link_selector"]):
            continue
        href = node.attributes.get("href")
        if not href:
            continue
        url = urljoin(str(resp.url), href).split("#")[0]
        if skip and skip.search(node.text(separator=" ")):
            finished.add(url)  # the listing marks it finished ("Ended", "Closed"); other links to it are skipped too
            continue
        if p.get("link_pattern") and not re.search(p["link_pattern"], url):
            continue
        urls.append(url)
    items = []
    for url in [u for u in dict.fromkeys(urls) if u not in finished][: int(p.get("max_items", 30))]:
        if is_known(url):
            continue
        try:
            items.append(page_item(source, url, http.get(url).text))
        except SourceFetchError as e:
            item_failed(item_errors, url, e)
    return items
