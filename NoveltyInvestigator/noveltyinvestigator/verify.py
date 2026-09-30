"""Check that a cited work says what the investigator quoted, by fetching it (our code, not the model)."""
from rqd.errors import SourceFetchError
from rqd.http import Fetcher, html_to_text, pdf_to_text
from rqd.quotes import quote_in_text


def verify_work(fetcher: Fetcher, url: str, quote: str) -> str:
    """'verified' | 'quote_not_found' (page read, quote absent) | 'unfetchable' (HTTP error, robots, timeout)."""
    try:
        resp = fetcher.get(url)
    except SourceFetchError:
        return "unfetchable"
    if "pdf" in resp.headers.get("content-type", "").lower() or resp.content[:5] == b"%PDF-":
        text = pdf_to_text(resp.content)
    else:
        text = html_to_text(resp.text, url)[0]
    return "verified" if quote_in_text(quote, text) else "quote_not_found"
