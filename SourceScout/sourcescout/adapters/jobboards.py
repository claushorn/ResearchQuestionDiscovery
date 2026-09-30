import html
from datetime import datetime, timezone

import httpx

from sourcescout.adapters.base import IsKnown, RawItem
from rqd.errors import SourceFetchError
from rqd.http import Fetcher, html_to_text
from sourcescout.registry import Source


def _json(resp: httpx.Response, url: str):
    try:
        return resp.json()
    except ValueError as e:
        raise SourceFetchError(f"{url}: invalid JSON ({e})") from e


def _shape_error(url: str, e: Exception) -> SourceFetchError:
    return SourceFetchError(f"{url}: unexpected response shape ({e!r})")


def fetch_greenhouse(source: Source, http: Fetcher, is_known: IsKnown,
                     item_errors: list[str] | None = None) -> list[RawItem]:
    data = _json(http.get(source.url), source.url)
    try:
        items = []
        for j in data["jobs"]:
            text, links = html_to_text(html.unescape(j.get("content") or ""), j["absolute_url"])
            items.append(RawItem(source.id, j["absolute_url"], j["title"] or "", j.get("updated_at"), text, tuple(links)))
        return items
    except (KeyError, TypeError) as e:
        raise _shape_error(source.url, e) from e


def fetch_lever(source: Source, http: Fetcher, is_known: IsKnown,
                item_errors: list[str] | None = None) -> list[RawItem]:
    data = _json(http.get(source.url), source.url)
    try:
        items = []
        for j in data:
            parts = [j.get("openingPlain"), j.get("descriptionPlain")]
            for lst in j.get("lists") or []:
                parts.append(f"{lst['text']}\n{html_to_text(lst.get('content') or '')[0]}")
            parts.append(j.get("additionalPlain"))
            created = j.get("createdAt")
            published = datetime.fromtimestamp(int(created) / 1000, timezone.utc).isoformat() if created else None
            items.append(RawItem(source.id, j["hostedUrl"], j["text"] or "", published, "\n\n".join(p for p in parts if p)))
        return items
    except (KeyError, TypeError, ValueError) as e:
        raise _shape_error(source.url, e) from e


def fetch_ashby(source: Source, http: Fetcher, is_known: IsKnown,
                item_errors: list[str] | None = None) -> list[RawItem]:
    data = _json(http.get(source.url), source.url)
    try:
        return [RawItem(source.id, j["jobUrl"], j["title"] or "", j.get("publishedAt"), j.get("descriptionPlain") or "")
                for j in data["jobs"] if j.get("isListed", True)]
    except (KeyError, TypeError) as e:
        raise _shape_error(source.url, e) from e
