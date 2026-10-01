import pytest

from conftest import make_fetcher
from sourcescout.adapters import KINDS, REQUIRED_PARAMS
from rqd.errors import SourceFetchError
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


def test_greenhouse_null_title_becomes_empty_string():
    data = {"jobs": [{"id": 1, "title": None, "absolute_url": "https://x.example/1", "content": ""}]}
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    assert KINDS["greenhouse"].fetch(S("greenhouse", url), make_fetcher({f"GET {url}": data}), never)[0].title == ""


def test_html_list_records_dead_item_and_keeps_others():
    routes = {"GET https://sbir.example/topics": LIST,
              "GET https://sbir.example/topics/2": "<html><head><title>Topic 2</title></head><body><main>Need RL</main></body></html>"}
    src = S("html_list", "https://sbir.example/topics", link_selector='a[href^="/topics/"]')
    errors: list[str] = []
    items = KINDS["html_list"].fetch(src, make_fetcher(routes), never, errors)
    assert [i.title for i in items] == ["Topic 2"]
    assert len(errors) == 1 and "topics/1" in errors[0] and "HTTP 404" in errors[0]


SECTIONED = """<html><body><h2>Prize competitions</h2><a href="/c/1">Open prize</a>
<h2>Benchmarks</h2><a href="/c/2">Benchmark</a><h2>Completed competitions</h2><a href="/c/3">Old one</a></body></html>"""
CARDS = """<html><body><a href="/c/1">Active · ends in 3 months Protein challenge</a>
<a href="/c/2">Ended · Results available Old challenge</a><a href="/c/2">Old challenge</a>
<a href="/c/3">Closed Another</a></body></html>"""


def _page(title):
    return f"<html><head><title>{title}</title></head><body><main>{title} body</main></body></html>"


def test_html_list_flags_items_below_the_completed_heading():
    routes = {"GET https://dd.example/competitions": SECTIONED, **{f"GET https://dd.example/c/{i}": _page(f"C{i}") for i in (1, 2, 3)}}
    src = S("html_list", "https://dd.example/competitions", link_selector='a[href^="/c/"]',
            finished_after_heading="(?i)completed competitions")
    items = KINDS["html_list"].fetch(src, make_fetcher(routes), never)
    assert [(i.title, i.finished) for i in items] == [("C1", False), ("C2", False), ("C3", True)]


def test_html_list_flags_links_whose_text_marks_them_finished():
    routes = {"GET https://pb.example/competitions": CARDS, **{f"GET https://pb.example/c/{i}": _page(f"C{i}") for i in (1, 2, 3)}}
    src = S("html_list", "https://pb.example/competitions", link_selector='a[href^="/c/"]',
            finished_link_text=r"(?i)\bended\b|\bclosed\b|\bcompleted\b")
    items = KINDS["html_list"].fetch(src, make_fetcher(routes), never)
    assert [(i.title, i.finished) for i in items] == [("C1", False), ("C2", True), ("C3", True)]


def test_known_item_that_finished_is_reported_without_refetching():
    routes = {"GET https://pb.example/competitions": CARDS}  # no item pages: known items must not be fetched
    src = S("html_list", "https://pb.example/competitions", link_selector='a[href^="/c/"]',
            finished_link_text=r"(?i)\bended\b|\bclosed\b")
    items = KINDS["html_list"].fetch(src, make_fetcher(routes), lambda u: True)
    assert [(i.url, i.finished, i.status_only) for i in items] == [
        ("https://pb.example/c/2", True, True), ("https://pb.example/c/3", True, True)]


def test_finished_listing_flags_every_entry():
    routes = {"GET https://ac.example/completed": '<a href="/c/1">One</a><a href="/c/2">Two</a>',
              **{f"GET https://ac.example/c/{i}": _page(f"C{i}") for i in (1, 2)}}
    src = S("html_list", "https://ac.example/completed", link_selector='a[href^="/c/"]', finished_listing=True)
    assert [(i.title, i.finished) for i in KINDS["html_list"].fetch(src, make_fetcher(routes), never)] == [
        ("C1", True), ("C2", True)]


# --- industry talks: one item per session, from JSON (feed or embedded) or from sections of one static page

import json as _json

NEXT = ("<html><body><script id=\"__NEXT_DATA__\" type=\"application/json\">" + _json.dumps({"props": {"pageProps": {
    "agenda": {"sessions": [
        {"id": 11, "title": "Precision Targeting at Scale", "body": "<p>How GM turns customer data into outcomes.</p>",
         "speakers": [{"name": "A", "company": "General Motors", "job_title": "Director"}], "slug": "precision"},
        {"id": 12, "title": "Make Me a Map", "body": "A GIS agent.", "speakers": [{"name": "B", "company": "Felt"}],
         "slug": "map"}]}}}}) + "</script></body></html>")

PRETALX = {"schedule": {"conference": {"days": [
    {"date": "2026-06-05", "rooms": {"Main": [{"guid": "g1", "title": "Document intelligence", "abstract": "Parsing PDFs.",
                                               "persons": [{"public_name": "C", "biography": "Works at Acme."}],
                                               "url": "https://pretalx.example/t/1/"}],
                                     "Side": []}},
    {"date": "2026-06-06", "rooms": {"Main": [{"guid": "g2", "title": "Forecasting retail demand", "abstract": "At Zalando.",
                                               "persons": [], "url": "https://pretalx.example/t/2/"}]}}]}}}


def test_json_sessions_from_embedded_next_data():
    src = S("json_sessions", "https://conf.example/agenda", embedded="script#__NEXT_DATA__",
            items_path="props.pageProps.agenda.sessions", title_field="title",
            text_fields=["body", "speakers.*.company", "speakers.*.job_title"], id_field="slug")
    items = KINDS["json_sessions"].fetch(src, make_fetcher({"GET https://conf.example/agenda": NEXT}), never)
    assert [(i.url, i.title) for i in items] == [("https://conf.example/agenda?talk=precision", "Precision Targeting at Scale"),
                                                 ("https://conf.example/agenda?talk=map", "Make Me a Map")]
    assert "How GM turns customer data into outcomes." in items[0].text and "General Motors" in items[0].text
    assert "<p>" not in items[0].text and "Director" in items[0].text


def test_json_sessions_relative_url_field_resolves_against_the_listing():
    src = S("json_sessions", "https://conf.example/agenda", embedded="script#__NEXT_DATA__",
            items_path="props.pageProps.agenda.sessions", title_field="title", text_fields=["body"], url_field="path")
    page = NEXT.replace('"slug": "precision"', '"slug": "precision", "path": "/session/precision"')
    items = KINDS["json_sessions"].fetch(src, make_fetcher({"GET https://conf.example/agenda": page}), never)
    assert items[0].url == "https://conf.example/session/precision" and items[1].url == "https://conf.example/agenda?talk=make-me-a-map"


def test_json_sessions_pretalx_nested_days_and_rooms_with_url_field():
    src = S("json_sessions", "https://pretalx.example/ev/schedule/export/schedule.json",
            items_path="schedule.conference.days.*.rooms.*.*", title_field="title",
            text_fields=["abstract", "persons.*.biography"], url_field="url", date_field="date")
    items = KINDS["json_sessions"].fetch(src, make_fetcher({"GET https://pretalx.example/ev/schedule/export/schedule.json": PRETALX}), never)
    assert [i.url for i in items] == ["https://pretalx.example/t/1/", "https://pretalx.example/t/2/"]
    assert "Works at Acme." in items[0].text


def test_json_sessions_skips_known_caps_and_rejects_a_wrong_path():
    src = S("json_sessions", "https://conf.example/agenda", embedded="script#__NEXT_DATA__",
            items_path="props.pageProps.agenda.sessions", title_field="title", text_fields=["body"], id_field="slug",
            max_items=1)
    f = make_fetcher({"GET https://conf.example/agenda": NEXT})
    assert [i.title for i in KINDS["json_sessions"].fetch(src, f, lambda u: u.endswith("?talk=precision"))] == ["Make Me a Map"]
    assert len(KINDS["json_sessions"].fetch(src, f, never)) == 1
    bad = S("json_sessions", "https://conf.example/agenda", embedded="script#__NEXT_DATA__",
            items_path="props.pageProps.sessions", title_field="title", text_fields=["body"], id_field="slug")
    with pytest.raises(SourceFetchError, match="items_path"):
        KINDS["json_sessions"].fetch(bad, f, never)
    with pytest.raises(SourceFetchError, match="script#__NEXT_DATA__"):
        KINDS["json_sessions"].fetch(src, make_fetcher({"GET https://conf.example/agenda": "<html>redesigned</html>"}), never)


SECTIONS = """<html><body><h1>Industry papers</h1>
<div class="paper" id="ind-1"><h3>Agentic Personalisation of Cross-Channel Marketing</h3><p>Authors (Aampe)</p>
<p>We personalise messages with agents.</p></div>
<div class="paper"><h3>Playlist curation with LLM query expansion</h3><p>(Japan Broadcasting Corporation)</p></div>
</body></html>"""


def test_html_sections_one_item_per_talk():
    src = S("html_sections", "https://conf.example/accepted", section_selector="div.paper", title_selector="h3")
    items = KINDS["html_sections"].fetch(src, make_fetcher({"GET https://conf.example/accepted": SECTIONS}), never)
    assert [i.title for i in items] == ["Agentic Personalisation of Cross-Channel Marketing",
                                        "Playlist curation with LLM query expansion"]
    assert items[0].url == "https://conf.example/accepted?talk=ind-1"
    assert items[1].url == "https://conf.example/accepted?talk=playlist-curation-with-llm-query-expansion"
    assert "Aampe" in items[0].text and "We personalise messages with agents." in items[0].text
    with pytest.raises(SourceFetchError, match="div.talk"):
        KINDS["html_sections"].fetch(S("html_sections", "https://conf.example/accepted", section_selector="div.talk"),
                                     make_fetcher({"GET https://conf.example/accepted": SECTIONS}), never)


def test_talk_adapters_declare_required_params():
    assert set(REQUIRED_PARAMS["json_sessions"]) == {"items_path", "title_field", "text_fields"}
    assert REQUIRED_PARAMS["html_sections"] == ("section_selector",)


def test_talks_without_their_own_page_get_distinct_store_ids():
    # measured: the store drops #fragments (canonical_url), so '#id' URLs collapsed every talk into one item
    from sourcescout.store import item_id_for
    src = S("html_sections", "https://conf.example/accepted", section_selector="div.paper", title_selector="h3")
    items = KINDS["html_sections"].fetch(src, make_fetcher({"GET https://conf.example/accepted": SECTIONS}), never)
    src2 = S("json_sessions", "https://conf.example/agenda", embedded="script#__NEXT_DATA__",
             items_path="props.pageProps.agenda.sessions", title_field="title", text_fields=["body"], id_field="slug")
    items += KINDS["json_sessions"].fetch(src2, make_fetcher({"GET https://conf.example/agenda": NEXT}), never)
    assert len({item_id_for(i.url) for i in items}) == len(items) == 4
