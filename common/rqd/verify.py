"""Check that a cited work says what the investigator quoted, by fetching it (our code, not the model)."""
from rqd.errors import SourceFetchError
from rqd.http import Fetcher, html_to_text, pdf_to_text
from rqd.quotes import quote_in_text, row_in_html


MIN_QUOTE_WORDS = 3  # "$" or "13%" alone would "verify" against almost any page


def verify_work(fetcher: Fetcher, url: str, quote: str, table: bool = False) -> str:
    """'verified' | 'quote_not_found' (page read, quote absent) | 'unfetchable' (HTTP error, robots, timeout)
    | 'quote_too_short' (fewer than MIN_QUOTE_WORDS words: not evidence of anything)
    | 'verified_row' (table=True, e.g. a leaderboard: see quotes.row_in_html)."""
    long_enough = len(quote.split()) >= MIN_QUOTE_WORDS
    if not long_enough and not table:
        return "quote_too_short"
    try:
        resp = fetcher.get(url)
        is_pdf = "pdf" in resp.headers.get("content-type", "").lower() or resp.content[:5] == b"%PDF-"
        text = pdf_to_text(resp.content) if is_pdf else html_to_text(resp.text, url)[0]
    except SourceFetchError:
        return "unfetchable"
    if long_enough and quote_in_text(quote, text):
        return "verified"
    if table and not is_pdf and row_in_html(quote, resp.text):
        return "verified_row"
    return "quote_not_found"
