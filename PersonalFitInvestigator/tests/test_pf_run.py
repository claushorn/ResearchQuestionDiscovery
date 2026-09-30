import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pf_testing import fit_output, make_profile, problem
from personalfit import cli
from personalfit.cli import app
from personalfit.config import PFPaths, load_config
from personalfit.run import PFContext, assess, is_stale
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import RqdError
from rqd.records import YamlStore
from rqd_testing import FakeRunner, agent_result, stream

PF_ROOT = Path(__file__).resolve().parents[1]


def session(output=None, **kw):
    return stream(agent_result(structured_output=output or fit_output(), **kw))


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "PersonalFitInvestigator"
    root.mkdir()
    shutil.copy(PF_ROOT / "config.yaml", root / "config.yaml")
    make_profile(tmp_path / "personal_profile")
    problems = YamlStore(tmp_path / "ProblemExtractor" / "problems")
    for pid in ("prob-a", "prob-b"):
        problems.save(problem(pid), pid)
    YamlStore(tmp_path / "NoveltyInvestigator" / "investigations").save(
        {"problem_id": "prob-a", "revision": 1, "novelty": {"status": "likely_open"}, "confidence": 0.7,
         "strongest_counterargument": "trigger upgrades may already solve it", "closest_work": []}, "prob-a")
    YamlStore(tmp_path / "EconomicValueInvestigator" / "assessments").save(
        {"problem_id": "prob-a", "revision": 1, "economic_value": {"beneficiary": {"type": "lab", "description": "LHC experiments"}},
         "confidence": 0.5}, "prob-a")
    return root


def context(root, outputs):
    paths = PFPaths(root)
    runner = FakeRunner(*outputs)
    return PFContext.open(paths, load_config(paths.config), ClaudeCodeClient(runner=runner), run_id="RUN1"), runner


def test_fit_record_and_agent_call(env):
    ctx, runner = context(env, [session()])
    assert assess(ctx, ["prob-a"]) == {}
    call = runner.calls[0]
    system = call["args"][call["args"].index("--system-prompt") + 1]
    assert "Founded the displaced-vertices group" in system and system.index('<file path="cv.md">') < system.index("<task>")
    assert call["args"][call["args"].index("--tools") + 1] == "" and "--allowedTools" not in call["args"]
    assert "Detect long-lived particles" in call["input"] and "trigger upgrades may already solve it" in call["input"]
    assert "LHC experiments" in call["input"]
    rec = ctx.fits.load("prob-a")
    assert rec["personal_advantage"]["score"] == 9 and rec["advantages"][0]["file"] == "cv.md"
    assert rec["problem_revision"] == 1 and rec["profile_digest"] == ctx.profile.digest
    assert rec["run"]["transcript"].startswith("prob-a-RUN1")


def test_unknown_problem_is_refused_before_any_spend(env):
    ctx, runner = context(env, [])
    with pytest.raises(RqdError, match="no problem prob-x"):
        assess(ctx, ["prob-a", "prob-x"])
    assert runner.calls == []


def test_agent_error_fails_one_problem_only(env):
    budget = stream(agent_result(subtype="error_max_budget_usd", is_error=True, terminal_reason="budget_exhausted",
                                 structured_output=None, errors=["Reached maximum budget ($0.5)"]))
    ctx, _ = context(env, [budget, session()])
    assert list(assess(ctx, ["prob-a", "prob-b"])) == ["prob-a"] and ctx.fits.exists("prob-b")


def test_schema_violation_fails_the_item(env):
    ctx, _ = context(env, [session(fit_output(personal_advantage=11)), session()])
    assert list(assess(ctx, ["prob-a", "prob-b"])) == ["prob-a"]


def test_stale_when_profile_or_problem_changes(env, tmp_path):
    ctx, _ = context(env, [session(), session()])
    assess(ctx, ["prob-a"])
    fit, prob = ctx.fits.load("prob-a"), ctx.problems.load("prob-a")
    assert not is_stale(fit, prob, ctx.profile)
    assert is_stale(fit, prob | {"revision": 2}, ctx.profile)
    (tmp_path / "personal_profile" / "notes.md").write_text("Taught himself to program at the age of 10.")
    ctx2, _ = context(env, [])
    assert is_stale(fit, prob, ctx2.profile)
    assess(ctx, ["prob-a"])
    assert ctx.fits.load("prob-a")["revision"] == 2 and len(ctx.fits.load("prob-a")["history"]) == 1


def test_cli_assess_list_show(env, monkeypatch):
    runner = FakeRunner(session())
    monkeypatch.setattr(cli, "make_agent_client", lambda: ClaudeCodeClient(runner=runner))
    r = CliRunner()
    res = r.invoke(app, ["--root", str(env), "assess", "prob-a"])
    assert res.exit_code == 0, res.output
    res = r.invoke(app, ["--root", str(env), "list"])
    assert "prob-a" in res.output and "9/10" in res.output and "Detect long-lived" in res.output
    assert "cv.md" in r.invoke(app, ["--root", str(env), "show", "prob-a"]).output
    res = r.invoke(app, ["--root", str(env), "show", "prob-zz"])
    assert res.exit_code == 1 and "ERROR:" in res.output
