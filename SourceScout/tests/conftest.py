import shutil
from pathlib import Path

import httpx
import pytest

from sourcescout.categories import load_categories
from sourcescout.config import HttpCfg, Paths
from sourcescout.http import Fetcher
from sourcescout.registry import Registry, Source

REPO_SCOUT = Path(__file__).resolve().parents[1]


@pytest.fixture
def paths(tmp_path) -> Paths:
    shutil.copy(REPO_SCOUT / "sources.yaml", tmp_path / "sources.yaml")
    shutil.copy(REPO_SCOUT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "registry.yaml").write_text("sources: []\n")
    return Paths(tmp_path)


def make_registry(paths: Paths, sources: list[dict], kinds: dict | None = None) -> Registry:
    if kinds is None:  # default kinds come from the adapters (Task 3)
        from sourcescout.adapters import REQUIRED_PARAMS
        kinds = REQUIRED_PARAMS
    cats = load_categories(paths.categories)
    return Registry(paths.registry, [Source.model_validate(s) for s in sources], cats, kinds)


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
