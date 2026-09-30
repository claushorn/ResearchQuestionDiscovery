from datetime import datetime, timezone

import httpx

from conftest import make_fetcher, make_registry
from sourcescout.config import LifecycleCfg
from sourcescout.lifecycle import apply_lifecycle
from sourcescout.report import ExtractStat, RunReport
from sourcescout.scan import scan
from sourcescout.store import Store

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
PAGE = "<html><head><title>{t}</title></head><body><p>{b}</p></body></html>"


def page_src(id, url, **params):
    return {"id": id, "name": id, "category": "tech_blog", "kind": "page", "url": url, "params": params}


def run_scan(reg, store, routes, **kw):
    report = RunReport.new(NOW)
    scan(reg, store, make_fetcher(routes), report, now=NOW, max_item_chars=1000, force=True, **kw)
    return report


def test_scan_new_unchanged_changed_and_failure_isolated(paths):
    reg = make_registry(paths, [page_src("ok", "https://a.example/p"), page_src("bad", "https://b.example/p")])
    store = Store(paths.db)
    routes = {"GET https://a.example/p": PAGE.format(t="T", b="v1"), "GET https://b.example/p": httpx.Response(500)}
    r1 = run_scan(reg, store, routes)
    assert r1.scan["ok"].new == 1 and "HTTP 500" in r1.scan["bad"].error
    assert reg.get("bad").health.consecutive_failures == 1
    assert reg.get("ok").yield_.scans == 1 and reg.get("ok").health.last_ok
    assert run_scan(reg, store, routes).scan["ok"].unchanged == 1
    routes["GET https://a.example/p"] = PAGE.format(t="T", b="v2")
    assert run_scan(reg, store, routes).scan["ok"].changed == 1
    assert "consecutive_failures: 3" in paths.registry.read_text()


def test_title_filter(paths):
    reg = make_registry(paths, [page_src("f", "https://a.example/p", title_exclude="(?i)sales")])
    report = run_scan(reg, Store(paths.db), {"GET https://a.example/p": PAGE.format(t="Sales Lead", b="x")})
    assert report.scan["f"].filtered == 1 and report.scan["f"].new == 0


def test_lifecycle_rules(paths):
    reg = make_registry(paths, [
        page_src("cand_hit", "https://a.example/1") | {"status": "candidate", "yield": {"scans": 2, "candidates": 1}},
        page_src("cand_miss", "https://a.example/2") | {"status": "candidate", "yield": {"scans": 5}},
        page_src("act_dry", "https://a.example/3") | {"yield": {"scans": 30, "scans_since_candidate": 20}},
        page_src("act_broken", "https://a.example/4") | {"health": {"consecutive_failures": 5, "last_error": "HTTP 404"}},
        page_src("act_fine", "https://a.example/5") | {"yield": {"scans": 30, "scans_since_candidate": 3}},
    ])
    msgs = apply_lifecycle(reg, LifecycleCfg(promote_within_scans=5, max_consecutive_failures=5, retire_zero_yield_active=20))
    status = {s.id: s.status for s in reg.sources}
    assert status == {"cand_hit": "active", "cand_miss": "retired", "act_dry": "retired",
                      "act_broken": "retired", "act_fine": "active"}
    assert len(msgs) == 4 and any("HTTP 404" in m for m in msgs)


def test_report_budget_and_roundtrip(paths):
    r = RunReport.new(NOW)
    r.extract["a"] = ExtractStat(items=2, candidates=2, output_tokens=1400)
    r.extract["b"] = ExtractStat(items=3, candidates=3, output_tokens=1100)
    r.extract["c"] = ExtractStat(items=1, candidates=0, output_tokens=200)
    v = r.budget_violations(500)
    assert v == {"a": 700.0, "ALL": 540.0}  # (1400+1100+200)/5
    path = r.save(paths.runs)
    again = RunReport.load(path)
    assert again.extract["a"].output_tokens == 1400 and RunReport.latest(paths.runs) == path
    text = again.render(500)
    assert "BUDGET VIOLATIONS" in text and "a" in text
