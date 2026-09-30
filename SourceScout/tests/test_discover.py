from datetime import datetime, timezone

import yaml

from conftest import make_fetcher, make_registry
from sourcescout.config import load_config
from sourcescout.discover import blog_like, discover, find_feed, job_board_source
from sourcescout.report import RunReport

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def test_job_board_patterns():
    s = job_board_source("https://job-boards.greenhouse.io/acme/jobs/123", "item1", "(?i)research")
    assert (s.id, s.kind, s.url, s.status, s.provenance, s.category) == (
        "greenhouse-acme", "greenhouse", "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
        "candidate", "discovered_from:item1", "job_board")
    assert s.params == {"title_include": "(?i)research"}
    assert job_board_source("https://jobs.lever.co/acme/abc", "i", "x").url == "https://api.lever.co/v0/postings/acme?mode=json"
    assert job_board_source("https://jobs.ashbyhq.com/acme", "i", "x").url == "https://api.ashbyhq.com/posting-api/job-board/acme"
    assert job_board_source("https://example.com/jobs", "i", "x") is None


def test_find_feed_and_blog_like():
    html = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>'
    assert find_feed(html, "https://eng.acme.example/post") == "https://eng.acme.example/feed.xml"
    assert find_feed("<html></html>", "https://x.example") is None
    assert blog_like("https://engineering.acme.example/x") and blog_like("https://acme.example/blog/x")
    assert not blog_like("https://acme.example/products")


def test_discover_adds_candidates_and_writes_unmapped(paths):
    reg = make_registry(paths, [{"id": "rss-known", "name": "k", "category": "tech_blog", "kind": "rss",
                                 "url": "https://known.example/feed"}])
    feed_page = '<html><head><link rel="alternate" type="application/atom+xml" href="https://blog.new.example/atom"></head></html>'
    routes = {"GET https://blog.new.example/post/1": feed_page,
              "GET https://corp.example/about": "<html><body>no feed</body></html>"}
    cfg = load_config(paths.config).discovery
    report = RunReport.new(NOW)
    refs = [("https://blog.new.example/post/1", "i1"), ("https://corp.example/about", "i2"),
            ("https://known.example/other", "i3"), ("https://twitter.com/acme", "i4")]
    links = [("https://jobs.lever.co/acme/1", "i5"), ("https://jobs.lever.co/acme/2", "i6")]
    discover(reg, make_fetcher(routes), cfg, refs, links, report, paths.unmapped)
    ids = {s.id for s in reg.sources}
    assert {"rss-blog-new-example", "lever-acme"} <= ids and len(ids) == 3
    assert reg.get("rss-blog-new-example").url == "https://blog.new.example/atom"
    assert set(report.discovered) == {"rss-blog-new-example", "lever-acme"}
    unmapped = yaml.safe_load(paths.unmapped.read_text())
    assert [u["url"] for u in unmapped] == ["https://corp.example/about"]
    # second run: nothing new, unmapped not duplicated
    discover(reg, make_fetcher(routes), cfg, refs, links, RunReport.new(NOW), paths.unmapped)
    assert len(reg.sources) == 3 and len(yaml.safe_load(paths.unmapped.read_text())) == 1
