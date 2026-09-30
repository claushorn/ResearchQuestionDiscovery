import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ev_testing import FACTORS, ev_output, problem, source
from economicvalue import cli
from economicvalue.assess import EVContext, assess
from economicvalue.cli import app
from economicvalue.config import EVPaths, load_config
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import ExtractionConfigError, RqdError
from rqd.records import YamlStore
from rqd_testing import FakeRunner, agent_result, make_fetcher, stream, tool_use

EV_ROOT = Path(__file__).resolve().parents[1]
PAGES = {"GET https://e.example/1": "<html><body>Report: 2,000 companies deploy agents today.</body></html>",
         "GET https://e.example/2": "<html><body>Acme: incidents cost us $40,000 each.</body></html>"}


def agent_stream(n_search=4, output=None, **kw):
    events = [tool_use("WebSearch", query=f"q{i}") for i in range(n_search)] + [tool_use("WebFetch", url="https://e.example/1")]
    return stream(*events, agent_result(structured_output=output or ev_output(estimates=FACTORS),
                                        modelUsage={"claude-opus-5-5": {}}, **kw))




@pytest.fixture
def env(tmp_path):
    root = tmp_path / "EconomicValueInvestigator"
    root.mkdir()
    shutil.copy(EV_ROOT / "config.yaml", root / "config.yaml")
    problems = YamlStore(tmp_path / "ProblemExtractor" / "problems")
    for pid in ("prob-a", "prob-b", "prob-s"):
        problems.save(problem(pid, sources=[source("grants-gov-ml", stated="Award ceiling: 250,000")]), pid)
    inv = YamlStore(tmp_path / "NoveltyInvestigator" / "investigations")
    inv.save({"problem_id": "prob-a", "novelty": {"status": "partially_solved"}, "strongest_counterargument": "c",
              "closest_work": []}, "prob-a")
    inv.save({"problem_id": "prob-s", "novelty": {"status": "solved"}, "strongest_counterargument": "done",
              "closest_work": []}, "prob-s")
    return root


def context(root, outputs):
    paths = EVPaths(root)
    runner = FakeRunner(*outputs)
    return EVContext.open(paths, load_config(paths.config), client=ClaudeCodeClient(runner=runner),
                          fetcher=make_fetcher(PAGES), run_id="RUN1"), runner


def test_assessment_record(env):
    ctx, runner = context(env, [agent_stream()])
    assert assess(ctx, ["prob-a"]) == {}
    rec = ctx.assessments.load("prob-a")
    ev = rec["economic_value"]
    assert rec["gate"] == "passed" and "partially_solved" in runner.calls[0]["input"] and "250000" in runner.calls[0]["input"]
    assert ev["beneficiary"] == {"type": "AI_startup", "description": "teams deploying LLM agents"}
    assert ev["pain"]["score"] == 8 and ev["buyer"] == "CTO / Head_of_Research"
    assert ev["deployment"] == {"assessment": "plausible", "barriers": "integration"}
    assert ev["urgency"]["level"] == "medium" and ev["current_cost"] == "unknown"
    assert ev["potential_value"]["low"] == pytest.approx(2000 * 2 * 40000 * 0.05)
    assert ev["potential_value"]["status"] == "assumption_only"
    assert [e["verification"] for e in rec["evidence"]] == ["verified", "verified"]
    assert rec["questions"]["who_has_problem"] == "AI startups" and rec["score"]["max_committed_usd"] == 250000
    assert rec["search"]["sufficient"] and rec["assessed_with"]["answered_by"] == ["claude-opus-5-5"]
    assert (env / "data" / "transcripts" / rec["assessed_with"]["transcript"]).exists()


def test_solved_problem_refused_before_any_spend_unless_forced(env):
    ctx, runner = context(env, [agent_stream()])
    with pytest.raises(RqdError, match="marked it solved"):
        assess(ctx, ["prob-a", "prob-s"])
    assert runner.calls == []
    assert assess(ctx, ["prob-s"], force=True) == {} and ctx.assessments.load("prob-s")["gate"] == "forced"


def test_not_investigated_problem_is_assessed_with_gate_noted(env):
    ctx, _ = context(env, [agent_stream()])
    assess(ctx, ["prob-b"])
    assert ctx.assessments.load("prob-b")["gate"] == "not_investigated"


def test_budget_error_writes_nothing_and_next_continues(env):
    budget = stream(agent_result(subtype="error_max_budget_usd", is_error=True, terminal_reason="budget_exhausted",
                                 structured_output=None, errors=["Reached maximum budget ($2)"]))
    ctx, _ = context(env, [budget, agent_stream()])
    failures = assess(ctx, ["prob-a", "prob-b"])
    assert list(failures) == ["prob-a"] and not ctx.assessments.exists("prob-a") and ctx.assessments.exists("prob-b")


def test_usage_limit_stops(env):
    limit = stream(agent_result(is_error=True, subtype="error_during_execution", api_error_status=429,
                                result="Claude AI usage limit reached", structured_output=None))
    ctx, _ = context(env, [limit])
    with pytest.raises(ExtractionConfigError):
        assess(ctx, ["prob-a", "prob-b"])


def test_reassessment_keeps_history(env):
    ctx, _ = context(env, [agent_stream(), agent_stream(output=ev_output(estimates=FACTORS, pain_score=5))])
    assess(ctx, ["prob-a"])
    assess(ctx, ["prob-a"])
    rec = ctx.assessments.load("prob-a")
    assert rec["revision"] == 2 and rec["economic_value"]["pain"]["score"] == 5
    assert rec["history"][0]["economic_value"]["pain"]["score"] == 8


def test_cli_score_assess_list_show(env, monkeypatch):
    monkeypatch.setattr(cli, "make_agent_client", lambda: ClaudeCodeClient(runner=FakeRunner(agent_stream(n_search=1))))
    monkeypatch.setattr(cli, "make_fetcher_for", lambda cfg: make_fetcher(PAGES))
    r = CliRunner()
    res = r.invoke(app, ["--root", str(env), "score"])
    assert res.exit_code == 0 and "prob-a" in res.output and "250,000" in res.output
    assert (env / "data" / "scores.yaml").exists()
    res = r.invoke(app, ["--root", str(env), "assess", "prob-a"])
    assert res.exit_code == 0 and "prob-a" in res.output
    res = r.invoke(app, ["--root", str(env), "list"])
    assert "prob-a" in res.output and "INSUFFICIENT SEARCH" in res.output and "assumption_only" in res.output
    assert "potential_value" in r.invoke(app, ["--root", str(env), "show", "prob-a"]).output
    res = r.invoke(app, ["--root", str(env), "assess", "prob-s"])
    assert res.exit_code == 1 and "ERROR:" in res.output and "--force" in res.output


def test_malformed_investigation_file_is_a_clean_error(env, tmp_path):
    YamlStore(tmp_path / "NoveltyInvestigator" / "investigations").save({"problem_id": "prob-b"}, "prob-b")
    ctx, runner = context(env, [])
    with pytest.raises(RqdError, match="malformed"):
        assess(ctx, ["prob-b"])


def test_wrong_problemextractor_root_is_a_clean_error(env):
    cfg = (env / "config.yaml").read_text().replace("problemextractor_root: ../ProblemExtractor", "problemextractor_root: ../Nope")
    (env / "config.yaml").write_text(cfg)
    res = CliRunner().invoke(app, ["--root", str(env), "score"])
    assert res.exit_code == 1 and "problems directory not found" in res.output and "Traceback" not in res.output
