import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml
from selectolax.parser import HTMLParser

from sourcescout.config import DiscoveryCfg
from rqd.errors import SourceFetchError
from rqd.http import Fetcher
from sourcescout.registry import Registry, Source
from sourcescout.report import RunReport
from sourcescout.store import canonical_url

_JOB_PATTERNS = [
    (re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/([A-Za-z0-9_-]+)"), "greenhouse",
     "https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true"),
    (re.compile(r"^https?://jobs\.lever\.co/([A-Za-z0-9_-]+)"), "lever",
     "https://api.lever.co/v0/postings/{t}?mode=json"),
    (re.compile(r"^https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"), "ashby",
     "https://api.ashbyhq.com/posting-api/job-board/{t}"),
]
log = logging.getLogger("sourcescout")
_FEED_TYPES = ("application/rss+xml", "application/atom+xml")


def job_board_source(url: str, origin: str) -> Source | None:
    for pattern, kind, api in _JOB_PATTERNS:
        m = pattern.match(url)
        if m:
            token = m.group(1)
            return Source(id=f"{kind}-{token.lower()}", name=f"{token} ({kind})", category="job_board", kind=kind,
                          url=api.format(t=token),
                          status="candidate", provenance=f"discovered_from:{origin}")
    return None


def find_feed(html: str, base_url: str) -> str | None:
    for link in HTMLParser(html).css('link[rel="alternate"]'):
        if (link.attributes.get("type") or "").lower() in _FEED_TYPES and link.attributes.get("href"):
            return urljoin(base_url, link.attributes["href"])
    return None


def blog_like(url: str) -> bool:
    p = urlsplit(url)
    return p.netloc.lower().startswith(("engineering.", "blog.", "tech.", "research.")) or \
        bool(re.search(r"/(blog|engineering)(/|$)", p.path))


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _ignored(host: str, cfg: DiscoveryCfg) -> bool:
    return any(host == h or host.endswith("." + h) for h in cfg.ignore_hosts)


def discover(registry: Registry, http: Fetcher, cfg: DiscoveryCfg, refs: list[tuple[str, str]],
             links: list[tuple[str, str]], report: RunReport, unmapped_path: Path) -> None:
    for url, origin in refs + links:
        s = job_board_source(url, origin)
        if s and registry.find(s.id) is None:
            registry.add(s)
            report.discovered.append(s.id)

    unmapped = (yaml.safe_load(unmapped_path.read_text(encoding="utf-8")) or []) if unmapped_path.exists() else []
    known_unmapped = {canonical_url(u["url"]) for u in unmapped}
    known_hosts = {_host(s.url) for s in registry.sources}
    fetches = 0
    for url, origin in refs:
        host = _host(url)
        if (not host or _ignored(host, cfg) or host in known_hosts or job_board_source(url, origin)
                or canonical_url(url) in known_unmapped):
            continue
        if fetches >= cfg.max_fetches_per_run:
            report.discovery_errors.append(f"fetch cap {cfg.max_fetches_per_run} reached; remaining references skipped")
            break
        fetches += 1
        known_hosts.add(host)
        log.info("[discover %d/%d] %s", fetches, cfg.max_fetches_per_run, url)
        try:
            resp = http.get(url)
        except SourceFetchError as e:
            report.discovery_errors.append(str(e))
            continue
        feed = find_feed(resp.text, str(resp.url))
        if feed and blog_like(url):
            sid = "rss-" + re.sub(r"[^a-z0-9]+", "-", host).strip("-")
            if registry.find(sid) is None:
                registry.add(Source(id=sid, name=host, category="tech_blog", kind="rss", url=feed,
                                    status="candidate", provenance=f"discovered_from:{origin}"))
                report.discovered.append(sid)
        else:
            unmapped.append({"url": url, "feed": feed, "discovered_from": origin})
            known_unmapped.add(canonical_url(url))
            report.unmapped.append(url)
    unmapped_path.write_text(yaml.safe_dump(unmapped, sort_keys=False), encoding="utf-8")
    registry.save()
