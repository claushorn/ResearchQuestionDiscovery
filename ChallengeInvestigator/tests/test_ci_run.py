import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ci_testing import evidence, headroom_output, investigate_output, val
from challengeinvestigator import cli
from challengeinvestigator.cli import app
from challengeinvestigator.config import CIPaths, load_config
from challengeinvestigator.run import CIContext, check_headroom, investigate
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import RqdError
from rqd_testing import FakeRunner, agent_result, make_fetcher, stream, tool_use
from sourcescout.adapters.base import RawItem
from sourcescout.store import Store, item_id_for

CI_ROOT = Path(__file__).resolve().parents[1]
CEIL = val("ceiling", 1.0, basis="definition", evidence=0, definition="accuracy is at most 1.0")
PAGES = {"GET https://c.example/1": "<html><body>Team X scored 0.9 on the private leaderboard!</body></html>",
         "GET https://c.example/2": "<html><body>Note: the organisers' baseline reached 0.5 accuracy.</body></html>",
         "GET https://c.example/repo": "<html><body>README: our 1st place solution scored 0.9 on the private leaderboard.</body></html>",
         "GET https://c.example/rumour": "<html><body>nothing here</body></html>",
         "GET https://c.example/solved": "<html><body>Final: Team X reached 0.97 accuracy.</body></html>"}


def session(output, n_search=2):
    return stream(*[tool_use("WebSearch", query=f"q{i}") for i in range(n_search)], agent_result(structured_output=output))


HEADROOM = headroom_output([val("winner", 0.9), CEIL, val("baseline", 0.5, evidence=2)])
SOLVED = headroom_output([val("winner", 0.97), CEIL], ev=[{"title": "LB", "url": "https://c.example/solved",
                                                          "kind": "leaderboard", "quote": "Team X reached 0.97 accuracy"}])


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "ChallengeInvestigator"
    root.mkdir()
    shutil.copy(CI_ROOT / "config.yaml", root / "config.yaml")
    store = Store(tmp_path / "SourceScout" / "data" / "scout.db")
    for n in ("a", "b"):
        store.upsert(RawItem("aicrowd-completed", f"https://aicrowd.example/{n}", f"Challenge {n}", None,
                             f"Challenge {n}: maximise accuracy", (), finished=True), "2026-09-30T00:00:00+00:00", 20000)
    store.upsert(RawItem("aicrowd", "https://aicrowd.example/active", "Active", None, "open", ()), "2026-09-30T00:00:00+00:00", 20000)
    return root


def context(root, outputs, pages=PAGES):
    paths = CIPaths(root)
    runner = FakeRunner(*outputs)
    return CIContext.open(paths, load_config(paths.config), client=ClaudeCodeClient(runner=runner),
                          fetcher=make_fetcher(pages), run_id="RUN1"), runner


A, B = item_id_for("https://aicrowd.example/a"), item_id_for("https://aicrowd.example/b")


def test_headroom_defaults_to_all_unchecked_finished_challenges(env):
    ctx, runner = context(env, [session(HEADROOM), session(SOLVED)])
    assert check_headroom(ctx) == {}
    rec = ctx.challenges.load(A)
    h = rec["headroom"]
    assert rec["challenge"]["title"] == "Challenge a" and "maximise accuracy" in runner.calls[0]["input"]
    assert h["verdict"] == "headroom" and h["normalized_headroom"] == pytest.approx(0.2)
    assert [e["verification"] for e in h["evidence"]] == ["verified", "verified"] and h["search"]["searches"] == 2
    assert ctx.challenges.load(B)["headroom"]["verdict"] == "solved"
    ctx2, runner2 = context(env, [])
    assert check_headroom(ctx2) == {} and runner2.calls == []  # nothing left unchecked


def test_active_or_unknown_ids_are_clean_errors(env):
    ctx, _ = context(env, [])
    with pytest.raises(RqdError, match="not a finished challenge"):
        check_headroom(ctx, [item_id_for("https://aicrowd.example/active")])


def test_investigate_refuses_solved_before_any_spend_unless_forced(env):
    ctx, runner = context(env, [session(HEADROOM), session(SOLVED)])
    check_headroom(ctx)
    ctx2, runner2 = context(env, [session(investigate_output(), n_search=4)])
    with pytest.raises(RqdError, match="solved"):
        investigate(ctx2, [A, B])
    assert runner2.calls == []
    assert investigate(ctx2, [B], force=True) == {}


def test_investigate_runs_headroom_first_and_filters_unbacked_content(env):
    ctx, runner = context(env, [session(HEADROOM), session(investigate_output(), n_search=4)])
    assert investigate(ctx, [A]) == {}
    assert len(runner.calls) == 2
    inv = ctx.challenges.load(A)["investigation"]
    assert [s["team"] for s in inv["solutions"]] == ["Team X"]
    assert inv["solutions"][0]["score"] == 0.9
    w = inv["warnings"]
    assert any("Team Y" in x for x in w["dropped_solutions"]) and any("Team Z" in x for x in w["dropped_solutions"])
    assert w["unsupported_numbers"] == ["ideas[2].why_it_could_win: 12.5%"]
    assert inv["ideas"][0]["expected_gain_assumption"].startswith("a few points")
    assert inv["search"]["sufficient"] is True


def test_budget_error_on_one_challenge_continues(env):
    budget = stream(agent_result(subtype="error_max_budget_usd", is_error=True, terminal_reason="budget_exhausted",
                                 structured_output=None, errors=["Reached maximum budget ($0.5)"]))
    ctx, _ = context(env, [budget, session(SOLVED)])
    failures = check_headroom(ctx)
    assert list(failures) == [A] and ctx.challenges.exists(B) and not ctx.challenges.exists(A)


def test_cli_headroom_list_investigate_show(env, monkeypatch):
    runner = FakeRunner(session(HEADROOM), session(SOLVED), session(investigate_output(), n_search=4))
    monkeypatch.setattr(cli, "make_agent_client", lambda: ClaudeCodeClient(runner=runner))
    monkeypatch.setattr(cli, "make_fetcher_for", lambda cfg: make_fetcher(PAGES))
    r = CliRunner()
    assert r.invoke(app, ["--root", str(env), "headroom"]).exit_code == 0
    res = r.invoke(app, ["--root", str(env), "list"])
    assert A in res.output and "headroom 20%" in res.output and "solved" in res.output
    res = r.invoke(app, ["--root", str(env), "investigate", B])
    assert res.exit_code == 1 and "ERROR:" in res.output and "--force" in res.output
    assert r.invoke(app, ["--root", str(env), "investigate", A]).exit_code == 0
    assert "ideas" in r.invoke(app, ["--root", str(env), "show", A]).output


def test_numbers_backed_by_the_headroom_check_are_not_flagged(env):
    out = investigate_output(summary="the winner scored 0.9 against a ceiling of 1.0 and a baseline of 0.5",
                             ideas=[])
    ctx, _ = context(env, [session(HEADROOM), session(out, n_search=4)])
    investigate(ctx, [A])
    assert ctx.challenges.load(A)["investigation"]["warnings"]["unsupported_numbers"] == []
