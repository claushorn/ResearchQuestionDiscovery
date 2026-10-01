import logging
from datetime import datetime, timezone

import httpx
from typer.testing import CliRunner

from conftest import make_fetcher, make_registry
from test_extract import FakeClient, add_item, cand, ctx, message  # noqa: F401  (fixture re-export)
from sourcescout.extract import run_extraction
from sourcescout.report import RunReport
from sourcescout.scan import scan
from sourcescout.store import Store

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def test_scan_logs_one_line_per_source_with_position_and_outcome(paths, caplog):
    reg = make_registry(paths, [
        {"id": "ok", "name": "ok", "category": "tech_blog", "kind": "page", "url": "https://a.example/p"},
        {"id": "bad", "name": "bad", "category": "tech_blog", "kind": "page", "url": "https://b.example/p"}])
    routes = {"GET https://a.example/p": "<html><head><title>T</title></head><body>x</body></html>",
              "GET https://b.example/p": httpx.Response(500)}
    with caplog.at_level(logging.INFO, logger="sourcescout"):
        scan(reg, Store(paths.db), make_fetcher(routes), RunReport.new(NOW), now=NOW, max_item_chars=1000, force=True)
    text = caplog.text
    assert "[scan 1/2] ok" in text and "[scan 2/2] bad" in text
    assert "1 new" in text and "HTTP 500" in text


def test_extract_logs_each_item(ctx, caplog):
    add_item(ctx)
    with caplog.at_level(logging.INFO, logger="sourcescout"):
        run_extraction(ctx, FakeClient([message({"candidates": [cand()]})]), batch=False)
    assert "[extract 1/1] g: Call 1" in caplog.text and "1 candidates" in caplog.text


def test_cli_prints_progress_to_stderr(paths):
    from sourcescout.cli import app
    paths.registry.write_text("sources: []\n")
    res = CliRunner().invoke(app, ["--root", str(paths.root), "scan"])
    assert res.exit_code == 0 and "scanning 0 due sources" in res.output


def test_second_concurrent_run_is_refused(paths):
    import fcntl
    from sourcescout.cli import app
    paths.runs.mkdir(parents=True, exist_ok=True)
    held = open(paths.root / "data" / "run.lock", "w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = CliRunner().invoke(app, ["--root", str(paths.root), "scan"])
    finally:
        held.close()
    assert res.exit_code == 1 and "another command is running on this directory" in res.output


def test_registry_saved_after_each_source_so_interrupts_keep_progress(paths, monkeypatch):
    import pytest
    from sourcescout import scan as scan_mod
    from sourcescout.adapters.base import Kind
    reg = make_registry(paths, [
        {"id": "first", "name": "f", "category": "tech_blog", "kind": "page", "url": "https://a.example/p"},
        {"id": "second", "name": "s", "category": "tech_blog", "kind": "page", "url": "https://b.example/p"}])
    real = scan_mod.KINDS["page"]

    def fetch(source, http, is_known, item_errors=None):
        if source.id == "second":
            raise KeyboardInterrupt
        return real.fetch(source, http, is_known, item_errors)
    monkeypatch.setitem(scan_mod.KINDS, "page", Kind(fetch))
    with pytest.raises(KeyboardInterrupt):
        scan(reg, Store(paths.db), make_fetcher({"GET https://a.example/p": "<html><body>x</body></html>"}),
             RunReport.new(NOW), now=NOW, max_item_chars=1000, force=True)
    assert "first:" in paths.registry_state.read_text() and "last_scanned: '2026-09-30T12:00:00+00:00'" in paths.registry_state.read_text()
