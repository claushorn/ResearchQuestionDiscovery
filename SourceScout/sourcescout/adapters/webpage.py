import re
from dataclasses import replace
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
    """Items of a listing page. Entries the listing marks finished (`finished_link_text` on any link to the URL,
    below a `finished_after_heading` heading, or everything when `finished_listing` is true) are returned with finished=True: stored for later use, never
    extracted. A known entry that became finished comes back as a status-only update (no refetch)."""
    p = source.params
    resp = http.get(source.url)
    below = re.compile(p["finished_after_heading"]) if p.get("finished_after_heading") else None
    marker = re.compile(p["finished_link_text"]) if p.get("finished_link_text") else None
    urls, finished = [], set()
    in_finished_section = bool(p.get("finished_listing"))  # a listing of finished entries only (e.g. ?filter=completed)
    for node in HTMLParser(resp.text).root.traverse():  # document order, so a heading can start the finished section
        if below and node.tag in _HEADINGS and below.search(node.text(separator=" ")):
            in_finished_section = True
            continue
        if node.tag != "a" or not node.css_matches(p["link_selector"]):
            continue
        href = node.attributes.get("href")
        if not href:
            continue
        url = urljoin(str(resp.url), href).split("#")[0]
        if p.get("link_pattern") and not re.search(p["link_pattern"], url):
            continue
        if in_finished_section or (marker and marker.search(node.text(separator=" "))):
            finished.add(url)  # any link to the URL marking it finished decides for all links to it
        urls.append(url)
    urls = list(dict.fromkeys(urls))
    cap = int(p.get("max_items", 30))
    selected = [u for u in urls if u not in finished][:cap] + [u for u in urls if u in finished][:cap]
    items = []
    for url in selected:
        done = url in finished
        if is_known(url):
            if done:
                items.append(RawItem(source.id, url, "", None, "", (), finished=True, status_only=True))
            continue
        try:
            item = page_item(source, url, http.get(url).text)
        except SourceFetchError as e:
            item_failed(item_errors, url, e)
            continue
        items.append(replace(item, finished=done))
    return items
