import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
import yaml

from conftest import make_registry
from sourcescout.adapters.base import RawItem
from sourcescout.config import load_config
from sourcescout.errors import ExtractionConfigError
from sourcescout.extract import (ExtractContext, build_params, make_client, quote_in_text, recent_referenced_links,
                                 run_extraction)
from sourcescout.report import RunReport
from sourcescout.store import Store, item_id_for

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
TEXT = "The agency seeks methods for “long-horizon planning”, which remains an open challenge.\nAwards up to $1.5M."


def message(payload, output_tokens=800, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=1200, output_tokens=output_tokens, cache_read_input_tokens=0))


def cand(unsolved='for "long-horizon planning", which remains an open challenge', pay="Awards up to $1.5M."):
    return {"statement": "Long-horizon planning methods.", "why_interesting": "Agency funds it.",
            "explicit_unsolved_signal": {"present": True, "evidence": unsolved},
            "payment_signal": {"type": "grant", "stated": "$1.5M", "evidence": pay, "deadline": "2026-12-01"},
            "technical_area": ["planning"], "entities": {"organizations": ["NSF"], "researchers": []}}


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **params):
        self.calls.append(params)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def ctx(paths):
    reg = make_registry(paths, [{"id": "g", "name": "G", "category": "gov_solicitation", "kind": "page",
                                 "url": "https://g.example"}])
    store = Store(paths.db)
    return ExtractContext(load_config(paths.config).extraction, reg, store, RunReport.new(NOW), paths.output, "RUN1")


def add_item(ctx, url="https://g.example/1"):
    ctx.store.upsert(RawItem("g", url, "Call 1", "2026-09-01", TEXT, ("https://org.example/call",)), "2026-09-30T00:00:00+00:00", 20000)


def test_build_params(ctx):
    add_item(ctx)
    [item] = ctx.store.pending()
    p = build_params(ctx.cfg, item, ctx.registry.get("g"), ctx.registry.categories["gov_solicitation"])
    assert p["model"] == "claude-opus-5-5" and p["max_tokens"] == 4000
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert p["output_config"]["effort"] == "low" and p["output_config"]["format"]["type"] == "json_schema"
    user = p["messages"][0]["content"]
    assert "long-horizon planning" in user and "https://org.example/call" in user and 'tier="A"' in user


def test_quote_in_text_normalises_quotes_and_whitespace():
    assert quote_in_text('for "long-horizon  planning", which', TEXT)
    assert not quote_in_text("the agency wants better planning", TEXT)
    assert not quote_in_text("", TEXT)
    assert quote_in_text("better forecasting.", "We need better\nforecasting\n.")


def test_sync_writes_records(ctx):
    add_item(ctx)
    client = FakeClient([message({"candidates": [cand(), cand(pay="paraphrased funding")]})])
    run_extraction(ctx, client, batch=False)
    files = sorted(ctx.output_dir.glob("*/*.yaml"))
    assert len(files) == 2
    recs = [yaml.safe_load(f.read_text()) for f in files]
    assert [r["evidence_verified"] for r in recs] == [True, False]
    r0 = recs[0]
    assert r0["source"] == {"url": "https://g.example/1", "title": "Call 1", "date": "2026-09-01",
                            "tier": "A", "category": "gov_solicitation"}
    assert r0["candidate_id"].endswith("-r1-0") and r0["extracted_with"]["output_tokens"] == 400
    st = ctx.report.extract["g"]
    assert (st.items, st.candidates, st.output_tokens, st.unverified) == (1, 2, 800, 1)
    assert ctx.store.pending() == [] and ctx.registry.get("g").yield_.candidates == 2
    assert ctx.registry.get("g").yield_.scans_since_candidate == 0


def test_zero_candidates_marks_done(ctx):
    add_item(ctx)
    run_extraction(ctx, FakeClient([message({"candidates": []}, output_tokens=50)]), batch=False)
    assert list(ctx.output_dir.glob("*/*.yaml")) == [] and ctx.store.pending() == []


@pytest.mark.parametrize("outcome, needle", [
    (message({"candidates": []}, stop_reason="max_tokens"), "max_tokens"),
    (message("not json"), "schema"),
    (message({"candidates": [cand()] * 4}), "schema"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "api"),
])
def test_item_failures_are_recorded_and_run_continues(ctx, outcome, needle):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    run_extraction(ctx, FakeClient([outcome, message({"candidates": [cand()]})]), batch=False)
    assert len(ctx.report.failures) == 1 and needle in ctx.report.failures[0]["error"]
    assert ctx.report.extract["g"].candidates == 1


def test_auth_error_is_config_error(ctx):
    add_item(ctx)
    err = anthropic.AuthenticationError("bad key", response=httpx2.Response(
        401, request=httpx2.Request("POST", "https://api.anthropic.com")), body=None)
    with pytest.raises(ExtractionConfigError):
        run_extraction(ctx, FakeClient([err]), batch=False)


def test_make_client_without_credentials(ctx, monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ExtractionConfigError):
        make_client(ctx.cfg.model_copy(update={"backend": "api"}))


def test_links_are_numbered_and_relevant_links_resolved_by_code(ctx):
    add_item(ctx)
    [item] = ctx.store.pending()
    p = build_params(ctx.cfg, item, ctx.registry.get("g"), ctx.registry.categories["gov_solicitation"])
    assert "[1] https://org.example/call" in p["messages"][0]["content"]
    run_extraction(ctx, FakeClient([message({"candidates": [cand() | {"relevant_links": [1, 7]}]})]), batch=False)
    [f] = ctx.output_dir.glob("*/*.yaml")
    rec = yaml.safe_load(f.read_text())
    assert rec["referenced_urls"] == ["https://org.example/call"] and rec["unresolved_link_refs"] == [7]
    assert recent_referenced_links(ctx.output_dir, NOW - timedelta(days=1)) == [
        ("https://org.example/call", item_id_for("https://g.example/1"))]


def test_pending_items_are_extracted_in_tier_order(ctx):
    from sourcescout.registry import Source
    ctx.registry.add(Source(id="blog", name="b", category="tech_blog", kind="page", url="https://b.example"))
    ctx.store.upsert(RawItem("blog", "https://b.example/1", "Blog post", None, TEXT, ()), "2026-09-29T00:00:00+00:00", 20000)
    add_item(ctx)  # tier A, seen later than the tier C blog post
    client = FakeClient([message({"candidates": []})])
    run_extraction(ctx, client, batch=False, limit=1)
    assert "Call 1" in client.calls[0]["messages"][0]["content"]
def test_tokens_of_empty_items_are_reported_separately(ctx):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    run_extraction(ctx, FakeClient([message({"candidates": []}, output_tokens=80),
                                    message({"candidates": [cand()]}, output_tokens=450)]), batch=False)
    st = ctx.report.extract["g"]
    assert (st.output_tokens, st.empty_output_tokens, st.tokens_per_candidate()) == (530, 80, 450)
