import httpx
import pytest

from rqd.http import pdf_to_text
from rqd.verify import verify_work
from rqd_testing import make_fetcher, pdf_bytes

HTML = "<html><body><p>AlphaFold predicts protein structures with atomic accuracy.</p></body></html>"


def test_pdf_to_text_extracts_page_text():
    assert "three-track network" in pdf_to_text(pdf_bytes("A three-track network for structure"))


@pytest.mark.parametrize("route, quote, expected", [
    (HTML, "predicts protein structures with atomic accuracy", "verified"),
    (HTML, "a sentence the page does not contain", "quote_not_found"),
    (httpx.Response(404), "any quoted text", "unfetchable"),
    (httpx.Response(200, content=pdf_bytes("A three-track network for structure"),
                    headers={"content-type": "application/pdf"}), "A three-track network", "verified"),
])
def test_verify_work(route, quote, expected):
    f = make_fetcher({"GET https://paper.example/x": route})
    assert verify_work(f, "https://paper.example/x", quote) == expected


def test_robots_disallow_is_unfetchable():
    f = make_fetcher({"GET https://paper.example/x": HTML}, robots="User-agent: *\nDisallow: /\n")
    assert verify_work(f, "https://paper.example/x", "with atomic accuracy") == "unfetchable"


@pytest.mark.parametrize("url", ["", "not a url", "ftp://paper.example/x"])
def test_model_supplied_non_http_url_is_unfetchable(url):
    assert verify_work(make_fetcher({}), url, "some quoted text") == "unfetchable"


def test_unparsable_pdf_is_unfetchable():
    f = make_fetcher({"GET https://paper.example/x": httpx.Response(200, content=b"%PDF-1.4 broken",
                                                                   headers={"content-type": "application/pdf"})})
    assert verify_work(f, "https://paper.example/x", "some quoted text") == "unfetchable"


def test_too_short_quote_is_not_verified():
    f = make_fetcher({"GET https://paper.example/x": HTML})
    assert verify_work(f, "https://paper.example/x", "$") == "quote_too_short"
    assert verify_work(f, "https://paper.example/x", "atomic accuracy") == "quote_too_short"
    assert verify_work(f, "https://paper.example/x", "structures with atomic accuracy") == "verified"


def test_leaderboard_rows_verify_as_rows():
    lb = "<html><body><table><tr><td>1</td><td>wulfebw</td><td>0.768</td></tr></table></body></html>"
    f = make_fetcher({"GET https://lb.example/x": lb})
    assert verify_work(f, "https://lb.example/x", "wulfebw 0.768", table=True) == "verified_row"
    assert verify_work(f, "https://lb.example/x", "wulfebw 0.768") == "quote_too_short"
    assert verify_work(f, "https://lb.example/x", "wulfebw 0.9", table=True) == "quote_not_found"
