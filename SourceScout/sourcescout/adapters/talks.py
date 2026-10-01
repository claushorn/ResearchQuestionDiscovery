"""Conference industry talks and applied papers: one item per session, so each talk is extracted on its own.

- json_sessions: a JSON feed (pretalx schedule export, sessions.json) or JSON embedded in a page
  (`embedded`: a CSS selector of the <script>, e.g. Next.js `script#__NEXT_DATA__`). `items_path` is a dotted
  path to the sessions; `*` steps into every element of a list or every value of a mapping.
- html_sections: one static page listing many talks; `section_selector` wraps one talk.
Sessions without a page of their own get the URL `<listing URL>?talk=<id>` (a query, not a #fragment: the store's
canonical URL drops fragments, which would merge every talk into one item)."""
import json
import re
from urllib.parse import quote, urljoin

from selectolax.parser import HTMLParser

from sourcescout.adapters.base import IsKnown, RawItem, item_failed
from rqd.errors import SourceFetchError
from rqd.http import Fetcher, html_to_text
from sourcescout.registry import Source

def _walk(value, path: list[str]) -> list:
    """All values at a dotted path; '*' fans out over list elements or mapping values. Missing keys yield nothing."""
    if not path:
        return [value]
    head, rest = path[0], path[1:]
    if head == "*":
        children = value if isinstance(value, list) else list(value.values()) if isinstance(value, dict) else []
        return [v for c in children for v in _walk(c, rest)]
    if isinstance(value, dict) and head in value:
        return _walk(value[head], rest)
    return []


def _text(value) -> str:
    return html_to_text(value)[0] if isinstance(value, str) and "<" in value else str(value)


def _talk_url(listing: str, key: str) -> str:
    return f"{listing}{'&' if '?' in listing else '?'}talk={quote(str(key), safe='')}"


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:80]


def _load_json(source: Source, body: str):
    selector = source.params.get("embedded")
    if selector:
        node = HTMLParser(body).css_first(selector)
        if node is None:
            raise SourceFetchError(f"{source.url}: embedded JSON {selector!r} not found (layout changed?)")
        body = node.text()
    try:
        return json.loads(body)
    except ValueError as e:
        raise SourceFetchError(f"{source.url}: invalid JSON ({e})") from e


def fetch_json_sessions(source: Source, http: Fetcher, is_known: IsKnown,
                        item_errors: list[str] | None = None) -> list[RawItem]:
    p = source.params
    data = _load_json(source, http.get(source.url).text)
    found = _walk(data, p["items_path"].split("."))
    found = [x for v in found for x in (v if isinstance(v, list) else [v])]  # a path may end at the list itself
    sessions = [s for s in found if isinstance(s, dict)]
    if not sessions:
        raise SourceFetchError(f"{source.url}: no sessions at items_path {p['items_path']!r} (layout changed?)")
    items = []
    for s in sessions:
        title = str(s.get(p["title_field"]) or "")
        if p.get("url_field") and s.get(p["url_field"]):
            url = urljoin(source.url, str(s[p["url_field"]]))
        else:
            key = s.get(p["id_field"]) if p.get("id_field") else None
            url = _talk_url(source.url, key if key not in (None, "") else _slug(title))
        if is_known(url):
            continue
        parts = [f"{field}: {_text(v)}" for field in p["text_fields"] for v in _walk(s, field.split("."))
                 if v not in (None, "", [])]
        date = s.get(p["date_field"]) if p.get("date_field") else None
        items.append(RawItem(source.id, url, title, str(date) if date else None, "\n".join(parts)))
        if len(items) >= int(p.get("max_items", 30)):
            break
    return items


def fetch_html_sections(source: Source, http: Fetcher, is_known: IsKnown,
                        item_errors: list[str] | None = None) -> list[RawItem]:
    p = source.params
    resp = http.get(source.url)
    sections = HTMLParser(resp.text).css(p["section_selector"])
    if not sections:
        raise SourceFetchError(f"{source.url}: section_selector {p['section_selector']!r} matched nothing (layout changed?)")
    items = []
    for node in sections:
        title_node = node.css_first(p.get("title_selector", "h1, h2, h3, h4, h5, h6"))
        title = title_node.text(strip=True) if title_node else ""
        anchor = node.attributes.get("id") or _slug(title)
        url = _talk_url(source.url, anchor)
        if not anchor or is_known(url):
            continue
        text, links = html_to_text(node.html, str(resp.url))
        items.append(RawItem(source.id, url, title, None, text, tuple(links)))
        if len(items) >= int(p.get("max_items", 30)):
            break
    return items


_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+")
OPENALEX = "https://api.openalex.org/works/doi:"  # open scholarly metadata (publisher pages such as ACM block scripts)


def _abstract(inverted: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}."""
    if not inverted:
        return ""
    words = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    return " ".join(word for _, word in words)


def fetch_doi_list(source: Source, http: Fetcher, is_known: IsKnown,
                   item_errors: list[str] | None = None) -> list[RawItem]:
    """An accepted-papers page that lists DOIs (e.g. KDD's applied data science track): one item per paper with
    title, abstract and author institutions from OpenAlex."""
    text = html_to_text(http.get(source.url).text, source.url)[0]
    dois = list(dict.fromkeys(d.rstrip(".,;)") for d in _DOI.findall(text)))
    if not dois:
        raise SourceFetchError(f"{source.url}: no DOIs on the page (layout changed?)")
    items = []
    for doi in dois:
        url = f"https://doi.org/{doi}"
        if is_known(url):
            continue
        try:
            work = http.get(OPENALEX + doi).json()
        except (SourceFetchError, ValueError) as e:
            item_failed(item_errors, url, e if isinstance(e, SourceFetchError) else SourceFetchError(f"{doi}: {e}"))
            continue
        authors = "; ".join(f"{a['author']['display_name']} ({', '.join(i['display_name'] for i in a.get('institutions') or [])})"
                            for a in work.get("authorships") or [])
        abstract = _abstract(work.get("abstract_inverted_index"))
        body = f"Abstract: {abstract}" if abstract else "(no abstract in OpenAlex)"
        items.append(RawItem(source.id, url, work.get("title") or doi, work.get("publication_date"),
                             f"{body}\nAuthors: {authors}"))
        if len(items) >= int(source.params.get("max_items", 30)):
            break
    return items
