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
