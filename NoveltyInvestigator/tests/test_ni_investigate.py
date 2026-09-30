import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ni_testing import ni_output, problem_record
from noveltyinvestigator import cli
from noveltyinvestigator.cli import app
from noveltyinvestigator.config import NIPaths, load_config
from noveltyinvestigator.investigate import NIContext, investigate
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import ExtractionConfigError, RqdError
from rqd.records import YamlStore
from rqd_testing import agent_result, make_fetcher, stream, tool_use

NI_ROOT = Path(__file__).resolve().parents[1]
PAGES = {"GET https://paper.example/af2": "<html><body>AlphaFold predicts protein structures with atomic accuracy.</body></html>",
         "GET https://paper.example/rf.pdf": "<html><body>something else</body></html>"}


def agent_stream(n_search=4, output=None, **result_kw):
    events = [tool_use("WebSearch", query=f"q{i}") for i in range(n_search)]
    events += [tool_use("WebFetch", url="https://paper.example/af2"), tool_use("StructuredOutput")]
    return stream(*events, agent_result(structured_output=output or ni_output(), **result_kw))


class Runner:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, args, *, input, env, cwd, timeout):
        self.calls.append(input)
        out = self.outputs.pop(0)
        return subprocess.CompletedProcess(args, 0 if '"is_error": false' in out else 1, stdout=out, stderr="")


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "NoveltyInvestigator"
    root.mkdir()
    shutil.copy(NI_ROOT / "config.yaml", root / "config.yaml")
    problems = YamlStore(tmp_path / "ProblemExtractor" / "problems")
    for pid in ("prob-a", "prob-b"):
        problems.save(problem_record(pid), pid)
    return root


def context(root, outputs):
    paths = NIPaths(root)
    runner = Runner(outputs)
    return NIContext.open(paths, load_config(paths.config), client=ClaudeCodeClient(runner=runner),
                          fetcher=make_fetcher(PAGES), run_id="RUN1"), runner


def test_investigation_record_with_counted_search_and_verified_evidence(env):
    ctx, runner = context(env, [agent_stream()])
    assert investigate(ctx, ["prob-a"]) == {}
    rec = ctx.investigations.load("prob-a")
    assert "Predict 3D protein structure" in runner.calls[0]
    assert rec["novelty"] == {"status": "partially_solved"} and rec["confidence"] == 0.8
    assert rec["checks"]["already_solved"]["answer"] == "partially"
    assert [w["verification"] for w in rec["closest_work"]] == ["verified", "quote_not_found"]
    assert rec["verified_fraction"] == 0.5
    assert rec["search"] == {"searches": 4, "fetches": 1, "queries": ["q0", "q1", "q2", "q3"], "sufficient": True}
    assert rec["investigated_with"]["cost_usd_equivalent"] == pytest.approx(0.1257) and rec["revision"] == 1
    transcript = env / "data" / "transcripts" / rec["investigated_with"]["transcript"]
    assert transcript.exists()


def test_too_few_searches_marked_insufficient(env):
    ctx, _ = context(env, [agent_stream(n_search=1)])
    investigate(ctx, ["prob-a"])
    assert ctx.investigations.load("prob-a")["search"]["sufficient"] is False


def test_reinvestigation_keeps_history(env):
    ctx, _ = context(env, [agent_stream(), agent_stream(output=ni_output(novelty_status="solved", confidence=0.9))])
    investigate(ctx, ["prob-a"])
    investigate(ctx, ["prob-a"])
    rec = ctx.investigations.load("prob-a")
    assert rec["revision"] == 2 and rec["novelty"]["status"] == "solved"
    assert rec["history"][0]["novelty"] == {"status": "partially_solved"} and rec["history"][0]["revision"] == 1


def test_budget_error_writes_nothing_and_next_problem_continues(env):
    budget = stream(tool_use("WebSearch", query="q"), agent_result(subtype="error_max_budget_usd", is_error=True,
                    terminal_reason="budget_exhausted", structured_output=None, errors=["Reached maximum budget ($2)"]))
    ctx, _ = context(env, [budget, agent_stream()])
    failures = investigate(ctx, ["prob-a", "prob-b"])
    assert list(failures) == ["prob-a"] and "budget" in failures["prob-a"] and not ctx.investigations.exists("prob-a")
    assert ctx.investigations.exists("prob-b")
    assert list((env / "data" / "transcripts").glob("prob-a-*"))  # failed session kept for audit


def test_usage_limit_stops(env):
    limit = stream(agent_result(is_error=True, subtype="error_during_execution", api_error_status=429,
                                result="Claude AI usage limit reached", structured_output=None))
    ctx, _ = context(env, [limit])
    with pytest.raises(ExtractionConfigError):
        investigate(ctx, ["prob-a", "prob-b"])


def test_unknown_problem_is_clean_error(env):
    ctx, _ = context(env, [])
    with pytest.raises(RqdError, match="no problem prob-zzz"):
        investigate(ctx, ["prob-zzz"])


def test_cli_investigate_list_show(env, monkeypatch):
    monkeypatch.setattr(cli, "make_agent_client", lambda: ClaudeCodeClient(runner=Runner([agent_stream(n_search=1)])))
    monkeypatch.setattr(cli, "make_fetcher_for", lambda cfg: make_fetcher(PAGES))
    runner = CliRunner()
    res = runner.invoke(app, ["--root", str(env), "investigate", "prob-a"])
    assert res.exit_code == 0 and "prob-a" in res.output and "partially_solved" in res.output
    res = runner.invoke(app, ["--root", str(env), "list"])
    assert "prob-a" in res.output and "INSUFFICIENT SEARCH" in res.output
    assert "strongest_counterargument" in runner.invoke(app, ["--root", str(env), "show", "prob-a"]).output
    res = runner.invoke(app, ["--root", str(env), "investigate", "prob-zzz"])
    assert res.exit_code == 1 and "ERROR: no problem prob-zzz" in res.output
