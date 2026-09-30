import pytest

from conftest import make_fetcher
from sourcescout.adapters import KINDS, REQUIRED_PARAMS
from sourcescout.errors import SourceFetchError
from sourcescout.registry import Source


def S(kind, url, **params):
    return Source(id=f"t-{kind}", name="t", category="tech_blog", kind=kind, url=url, params=params)


never = lambda url: False  # noqa: E731

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Eng</title>
<item><title>Scaling ranking</title><link>https://eng.example/p/1</link>
<description>&lt;p&gt;Our &lt;a href="https://eng.example/data"&gt;dataset&lt;/a&gt; is hard.&lt;/p&gt;</description>
<pubDate>Mon, 28 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>No link</title></item></channel></rss>"""


def test_rss_summary_mode_and_skips_linkless():
    f = make_fetcher({"GET https://eng.example/feed": RSS})
    items = KINDS["rss"].fetch(S("rss", "https://eng.example/feed"), f, never)
    assert len(items) == 1
    it = items[0]
    assert (it.url, it.title) == ("https://eng.example/p/1", "Scaling ranking")
    assert "dataset is hard" in it.text.replace("\n", " ")
    assert it.links == ("https://eng.example/data",)


def test_rss_fetch_full_skips_known():
    f = make_fetcher({"GET https://eng.example/feed": RSS,
                      "GET https://eng.example/p/1": "<html><body><p>Full article body</p></body></html>"})
    src = S("rss", "https://eng.example/feed", fetch_full=True)
    assert "Full article body" in KINDS["rss"].fetch(src, f, never)[0].text
    assert KINDS["rss"].fetch(src, f, lambda u: True) == []


def test_rss_garbage_raises():
    f = make_fetcher({"GET https://eng.example/feed": "<<<not xml"})
    with pytest.raises(SourceFetchError):
        KINDS["rss"].fetch(S("rss", "https://eng.example/feed"), f, never)


def test_greenhouse():
    data = {"jobs": [{"id": 1, "title": "Research Scientist, RL", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
                      "updated_at": "2026-09-01T00:00:00-04:00",
                      "content": "&lt;p&gt;Solve long-horizon planning.&lt;/p&gt;"}]}
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    items = KINDS["greenhouse"].fetch(S("greenhouse", url), make_fetcher({f"GET {url}": data}), never)
    assert items[0].title == "Research Scientist, RL" and items[0].text == "Solve long-horizon planning."


def test_lever():
    data = [{"id": "a", "text": "ML Engineer", "hostedUrl": "https://jobs.lever.co/acme/a", "createdAt": 1786469891368,
             "openingPlain": "Intro", "descriptionPlain": "Build forecasting.",
             "lists": [{"text": "You will", "content": "<li>Beat baselines</li>"}], "additionalPlain": "Benefits"}]
    url = "https://api.lever.co/v0/postings/acme?mode=json"
    it = KINDS["lever"].fetch(S("lever", url), make_fetcher({f"GET {url}": data}), never)[0]
    assert it.url == "https://jobs.lever.co/acme/a" and it.published.startswith("2026-")
    assert "Build forecasting." in it.text and "Beat baselines" in it.text


def test_ashby_skips_unlisted():
    data = {"jobs": [{"id": "1", "title": "RS", "jobUrl": "https://jobs.ashbyhq.com/acme/1", "publishedAt": "2026-03-12T16:38:15+00:00",
                      "descriptionPlain": "Protein design.", "isListed": True},
                     {"id": "2", "title": "Hidden", "jobUrl": "https://jobs.ashbyhq.com/acme/2", "publishedAt": None,
                      "descriptionPlain": "x", "isListed": False}]}
    url = "https://api.ashbyhq.com/posting-api/job-board/acme"
    items = KINDS["ashby"].fetch(S("ashby", url), make_fetcher({f"GET {url}": data}), never)
    assert [i.title for i in items] == ["RS"]


def test_jobboard_bad_shape_raises():
    url = "https://api.ashbyhq.com/posting-api/job-board/acme"
    with pytest.raises(SourceFetchError, match="unexpected response shape"):
        KINDS["ashby"].fetch(S("ashby", url), make_fetcher({f"GET {url}": {"nope": 1}}), never)


def test_grants_gov():
    search = "https://api.grants.gov/v1/api/search2"
    detail = "https://api.grants.gov/v1/api/fetchOpportunity"
    routes = {
        f"POST {search}": {"data": {"oppHits": [{"id": "353936", "number": "24-569", "title": "MFAI",
                                                  "agency": "NSF", "closeDate": "10/09/2026", "oppStatus": "posted"}]}},
        f"POST {detail}": {"data": {"synopsis": {"synopsisDesc": "<p>Foundations of AI are unsolved.</p>",
                                                  "awardCeilingFormatted": "$1,500,000", "estimatedFundingFormatted": "$8,500,000"}}},
    }
    src = S("grants_gov", search, keyword="machine learning")
    it = KINDS["grants_gov"].fetch(src, make_fetcher(routes), never)[0]
    assert it.url == "https://www.grants.gov/search-results-detail/353936"
    assert "Award ceiling: $1,500,000" in it.text and "Foundations of AI are unsolved." in it.text
    assert KINDS["grants_gov"].fetch(src, make_fetcher(routes), lambda u: True) == []


LIST = """<html><body><a href="/topics/1">T1</a><a href="/topics/2">T2</a><a href="/about">About</a></body></html>"""


def test_html_list_follows_selector_and_skips_known():
    routes = {"GET https://sbir.example/topics": LIST,
              "GET https://sbir.example/topics/1": "<html><head><title>Topic 1</title></head><body><main>Need sensors</main></body></html>",
              "GET https://sbir.example/topics/2": "<html><head><title>Topic 2</title></head><body><main>Need RL</main></body></html>"}
    src = S("html_list", "https://sbir.example/topics", link_selector='a[href^="/topics/"]', content_selector="main")
    items = KINDS["html_list"].fetch(src, make_fetcher(routes), lambda u: u.endswith("/2"))
    assert [(i.title, i.text) for i in items] == [("Topic 1", "Need sensors")]


def test_page_content_selector_missing_raises():
    f = make_fetcher({"GET https://yc.example/rfs": "<html><body><p>x</p></body></html>"})
    with pytest.raises(SourceFetchError, match="content_selector"):
        KINDS["page"].fetch(S("page", "https://yc.example/rfs", content_selector="main"), f, never)


def test_required_params_exposed():
    assert REQUIRED_PARAMS["grants_gov"] == ("keyword",)
    assert REQUIRED_PARAMS["html_list"] == ("link_selector",)
    assert set(REQUIRED_PARAMS) == set(KINDS)
