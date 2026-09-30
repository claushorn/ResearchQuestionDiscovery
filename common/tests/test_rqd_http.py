import httpx
import pytest

from rqd_testing import make_fetcher
from rqd.config import HttpCfg
from rqd.errors import SourceFetchError
from rqd.http import Fetcher, html_to_text


def test_html_to_text_strips_boilerplate_and_resolves_links():
    html = """<html><head><script>var x=1</script><style>p{}</style></head>
    <body><nav><a href="/menu">Menu</a></nav><h1>Title</h1>
    <p>We  need   better <b>forecasting</b>.</p><a href="/call">Call</a><a href="/call">dup</a>
    <a href="mailto:x@y.z">mail</a><footer>foot</footer></body></html>"""
    text, links = html_to_text(html, "https://org.example/news/1")
    assert "var x" not in text and "Menu" not in text and "foot" not in text
    assert "Title" in text and "forecasting" in text
    assert links == ["https://org.example/call"]


def test_get_ok_and_http_error():
    f = make_fetcher({"GET https://a.example/ok": "hello", "GET https://a.example/boom": httpx.Response(500)})
    assert f.get("https://a.example/ok").text == "hello"
    with pytest.raises(SourceFetchError, match="HTTP 500"):
        f.get("https://a.example/boom")


def test_network_error_becomes_source_fetch_error():
    req = httpx.Request("GET", "https://a.example/x")
    f = make_fetcher({"GET https://a.example/x": httpx.ConnectError("refused", request=req)})
    with pytest.raises(SourceFetchError, match="refused"):
        f.get("https://a.example/x")


def test_robots_disallow():
    f = make_fetcher({"GET https://a.example/private/x": "secret"},
                     robots="User-agent: *\nDisallow: /private/\n")
    with pytest.raises(SourceFetchError, match="robots.txt disallows"):
        f.get("https://a.example/private/x")


def test_robots_server_error_blocks():
    def handler(request):
        return httpx.Response(503)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    f = Fetcher(HttpCfg(user_agent="t", timeout_s=5, min_interval_s_per_host=0), client=client, sleep=lambda s: None)
    with pytest.raises(SourceFetchError, match="robots.txt"):
        f.get("https://a.example/x")


def test_throttle_per_host():
    sleeps: list[float] = []
    def handler(request):
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, text="ok")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    f = Fetcher(HttpCfg(user_agent="t", timeout_s=5, min_interval_s_per_host=2.0),
                client=client, sleep=sleeps.append, clock=lambda: 100.0)
    f.get("https://a.example/1")
    f.get("https://a.example/2")
    assert sleeps and all(s == 2.0 for s in sleeps)


def test_http_error_carries_the_status():
    f = make_fetcher({})
    with pytest.raises(SourceFetchError) as e:
        f.get("https://a.example/missing")
    assert e.value.status == 404
