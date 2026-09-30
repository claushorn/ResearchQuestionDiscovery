"""Test helpers shared by all capability test suites (unique module name: no conftest collisions)."""
import httpx

from rqd.config import HttpCfg
from rqd.http import Fetcher


def make_fetcher(routes: dict, robots: str | None = None, sleeps: list | None = None) -> Fetcher:
    """routes: {"GET https://x/y": str | dict | list | httpx.Response | Exception}"""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots) if robots is not None else httpx.Response(404)
        value = routes.get(f"{request.method} {url}")
        if value is None:
            return httpx.Response(404)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        if isinstance(value, (dict, list)):
            return httpx.Response(200, json=value)
        return httpx.Response(200, text=value)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    record = sleeps if sleeps is not None else []
    return Fetcher(HttpCfg(user_agent="test-agent", timeout_s=5, min_interval_s_per_host=0.0),
                   client=client, sleep=record.append)
