import io
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from pypdf import PdfReader
from selectolax.parser import HTMLParser

from rqd.config import HttpCfg
from rqd.errors import SourceFetchError

_BOILERPLATE = ("script", "style", "noscript", "nav", "footer", "header", "svg", "form")


def html_to_text(html: str, base_url: str = "") -> tuple[str, list[str]]:
    """Visible text (one line per block, whitespace collapsed) and absolute outbound links."""
    tree = HTMLParser(html)
    for tag in _BOILERPLATE:
        for node in tree.css(tag):
            node.decompose()
    links = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        links.append(urljoin(base_url, href).split("#")[0])
    root = tree.body or tree.root
    raw = root.text(separator="\n") if root is not None else ""
    lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in raw.splitlines())
    return "\n".join(line for line in lines if line), list(dict.fromkeys(links))


def pdf_to_text(data: bytes) -> str:
    """Text of all pages of a PDF (for verifying quotes from papers served as PDF)."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


class Fetcher:
    """Polite HTTP client: robots.txt (RFC 9309), per-host throttle, errors -> SourceFetchError."""

    def __init__(self, cfg: HttpCfg, client: httpx.Client | None = None, sleep=time.sleep, clock=time.monotonic):
        self._cfg = cfg
        self._client = client or httpx.Client(timeout=cfg.timeout_s, follow_redirects=True)
        self._client.headers["User-Agent"] = cfg.user_agent
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: dict[str, float] = {}

    def get(self, url: str) -> httpx.Response:
        return self._request("GET", url)

    def post_json(self, url: str, payload: dict) -> httpx.Response:
        return self._request("POST", url, json=payload)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        self._check_robots(url)
        self._throttle(urlsplit(url).netloc)
        try:
            resp = self._client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise SourceFetchError(f"{method} {url}: {e}") from e
        if resp.status_code >= 400:
            raise SourceFetchError(f"{method} {url}: HTTP {resp.status_code}")
        return resp

    def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            self._throttle(parts.netloc)
            try:
                resp = self._client.get(base + "/robots.txt")
            except httpx.HTTPError as e:
                raise SourceFetchError(f"robots.txt unreachable for {base}: {e}") from e
            if resp.status_code >= 500:
                raise SourceFetchError(f"robots.txt for {base}: HTTP {resp.status_code} (treated as disallow)")
            if resp.status_code >= 400:
                self._robots[base] = None  # RFC 9309: unavailable robots.txt -> allow
            else:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                self._robots[base] = rp
        rp = self._robots[base]
        if rp is not None and not rp.can_fetch(self._cfg.user_agent, url):
            raise SourceFetchError(f"robots.txt disallows {url}")

    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self._cfg.min_interval_s_per_host - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()
