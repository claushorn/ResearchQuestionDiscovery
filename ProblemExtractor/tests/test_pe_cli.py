import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pe_testing import FakeClient, candidate, message, pe_output, seed
from problemextractor import cli
from problemextractor.cli import app

PE_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "ProblemExtractor"
    r.mkdir()
    shutil.copy(PE_ROOT / "config.yaml", r / "config.yaml")
    return r


def test_run_list_show(root, tmp_path, monkeypatch):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    monkeypatch.setattr(cli, "make_client", lambda backend: FakeClient([message(pe_output())]))
    res = runner.invoke(app, ["--root", str(root), "run"])
    assert res.exit_code == 0 and "candidates processed: 1" in res.output and "new problems: 1" in res.output
    res = runner.invoke(app, ["--root", str(root), "list"])
    pid = "prob-" + c["candidate_id"].removeprefix("cand-")
    assert res.exit_code == 0 and pid in res.output and "$1.5M" in res.output
    res = runner.invoke(app, ["--root", str(root), "show", pid])
    assert res.exit_code == 0 and "precise_statement" in res.output


def test_missing_sourcescout_store_is_clean_error(root):
    res = runner.invoke(app, ["--root", str(root), "run"])
    assert res.exit_code == 1 and "SourceScout store not found" in res.output and "Traceback" not in res.output


def test_show_unknown_problem_is_clean_error(root):
    res = runner.invoke(app, ["--root", str(root), "show", "prob-nope"])
    assert res.exit_code == 1 and "ERROR: no problem prob-nope" in res.output


def test_run_refused_while_sourcescout_runs(root, tmp_path, monkeypatch):
    import fcntl
    seed(tmp_path / "SourceScout", [candidate(0)])
    monkeypatch.setattr(cli, "make_client", lambda backend: FakeClient([message(pe_output())]))
    held = open(tmp_path / "SourceScout" / "data" / "run.lock", "w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = runner.invoke(app, ["--root", str(root), "run"])
    finally:
        held.close()
    assert res.exit_code == 1 and "another command is running" in res.output


def test_list_rejects_unknown_sort(root):
    res = runner.invoke(app, ["--root", str(root), "list", "--sort", "foo"])
    assert res.exit_code != 0 and "foo" in res.output


def test_list_flags_problems_whose_deadlines_all_passed(root, tmp_path, monkeypatch):
    from datetime import date
    from rqd.records import YamlStore
    import problemextractor.cli as pe_cli
    monkeypatch.setattr(pe_cli, "today", lambda: date(2026, 9, 30))
    c = candidate(0)
    rec = {"problem_id": "prob-x", "revision": 1, "problem": {"precise_statement": "Old call"},
           "sources": [{"candidate_id": c["candidate_id"], "source_id": "sbir-topics", "tier": "A", "url": "u", "title": "t",
                        "payment_signal": {"type": "contract", "stated": "", "deadline": "2026-07-10"}}]}
    YamlStore(root / "problems").save(rec, "prob-x")
    res = runner.invoke(app, ["--root", str(root), "list"])
    assert "prob-x" in res.output and "DUE PASSED" in res.output


def test_run_candidate_option_is_repeatable(root, tmp_path, monkeypatch):
    cs = [candidate(0), candidate(1), candidate(2)]
    seed(tmp_path / "SourceScout", cs)
    monkeypatch.setattr(cli, "make_client", lambda backend: FakeClient([message(pe_output()), message(pe_output())]))
    res = runner.invoke(app, ["--root", str(root), "run", "--candidate", cs[2]["candidate_id"],
                              "--candidate", cs[0]["candidate_id"]])
    assert res.exit_code == 0 and "candidates processed: 2" in res.output
    res = runner.invoke(app, ["--root", str(root), "run", "--candidate", "cand-nope"])
    assert res.exit_code == 1 and "ERROR:" in res.output and "cand-nope" in res.output and "Traceback" not in res.output
