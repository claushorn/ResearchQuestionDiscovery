import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ci_testing import aicrowd_page, baseline_output, drivendata_page, drivendata_partial, investigate_output
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
A_URL, B_URL, C_URL = ("https://www.aicrowd.com/challenges/a", "https://www.drivendata.org/competitions/1/b/",
                       "https://proteinbase.com/competitions/c")
A, B, C = item_id_for(A_URL), item_id_for(B_URL), item_id_for(C_URL)
PAGES = {f"GET {A_URL}/leaderboards": aicrowd_page("Accuracy", [("Team X", "0.900"), ("Team Y", "0.880")],
                                                   baselines=[("starter kit", "0.500")]),
         f"GET {B_URL}leaderboard/": drivendata_page("b"),
         "GET https://www.drivendata.org/competitions/1/b/leaderboard_partial/?page=1":
             drivendata_partial("Log Loss", [("TheAvengers", "0.2532"), ("NavAttack", "0.2731")]),
         "GET https://blog.example/bench": "<p>The benchmark model achieves a log loss of 0.6 on the test set.</p>",
         "GET https://c.example/repo": "<html><body>README: our 1st place solution scored 0.9 on the private leaderboard.</body></html>",
         "GET https://c.example/y": "<html><body>Team Y: self-play with a league of past agents.</body></html>",
         "GET https://c.example/rumour": "<html><body>nothing here</body></html>"}
SOLVED_PAGES = PAGES | {f"GET {A_URL}/leaderboards": aicrowd_page("Accuracy", [("Team X", "0.970"), ("Team Y", "0.950")])}


def session(output, n_search=2):
    return stream(*[tool_use("WebSearch", query=f"q{i}") for i in range(n_search)], agent_result(structured_output=output))


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "ChallengeInvestigator"
    root.mkdir()
    shutil.copy(CI_ROOT / "config.yaml", root / "config.yaml")
    store = Store(tmp_path / "SourceScout" / "data" / "scout.db")
    for source, url in (("aicrowd-completed", A_URL), ("drivendata", B_URL), ("proteinbase-competitions", C_URL)):
        store.upsert(RawItem(source, url, f"Challenge {url[-3:]}", None, "maximise accuracy", (), finished=True),
                     "2026-09-30T00:00:00+00:00", 20000)
    store.upsert(RawItem("aicrowd", "https://www.aicrowd.com/challenges/active", "Active", None, "open", ()),
                 "2026-09-30T00:00:00+00:00", 20000)
    return root


def context(root, outputs, pages=PAGES):
    paths = CIPaths(root)
    runner = FakeRunner(*outputs)
    return CIContext.open(paths, load_config(paths.config), client=ClaudeCodeClient(runner=runner),
                          fetcher=make_fetcher(pages), run_id="RUN1"), runner


def test_headroom_is_scraped_and_the_agent_only_looks_up_a_missing_baseline(env):
    ctx, runner = context(env, [session(baseline_output(), n_search=1)])
    assert check_headroom(ctx) == {}
    a = ctx.challenges.load(A)["headroom"]
    assert a["verdict"] == "headroom" and a["normalized_headroom"] == pytest.approx(0.2)
    assert a["winner"] == {"value": 0.9, "team": "Team X"} and a["baseline"]["basis"]["type"] == "leaderboard"
    assert a["leaderboard"]["url"] == f"{A_URL}/leaderboards" and a["baseline_lookup"] is None
    b = ctx.challenges.load(B)["headroom"]
    assert len(runner.calls) == 1 and "Log Loss" in runner.calls[0]["input"]  # the only agent call
    assert b["baseline"]["value"] == 0.6 and b["baseline"]["basis"]["verification"] == "verified"
    assert b["normalized_headroom"] == pytest.approx(0.2532 / 0.6) and b["baseline_lookup"]["search"]["searches"] == 1
    c = ctx.challenges.load(C)["headroom"]
    assert c["verdict"] == "not_applicable" and "proteinbase-competitions" in c["warnings"][0]
    ctx2, runner2 = context(env, [])
    assert check_headroom(ctx2) == {} and runner2.calls == []  # nothing left unchecked


def test_unbacked_baseline_lookup_leaves_it_unclear(env):
    ctx, _ = context(env, [session(baseline_output(value=0.55))])  # 0.55 is not in the quote
    check_headroom(ctx, [B])
    b = ctx.challenges.load(B)["headroom"]
    assert b["verdict"] == "unclear" and b["baseline"] is None and any("0.55" in w for w in b["warnings"])
    ctx, _ = context(env, [session(baseline_output(url="https://c.example/rumour"))])  # quote not on the page
    check_headroom(ctx, [B])
    assert ctx.challenges.load(B)["headroom"]["verdict"] == "unclear"


def test_layout_failure_or_budget_error_fails_that_challenge_only(env):
    budget = stream(agent_result(subtype="error_max_budget_usd", is_error=True, terminal_reason="budget_exhausted",
                                 structured_output=None, errors=["Reached maximum budget ($0.3)"]))
    ctx, _ = context(env, [budget], pages=PAGES | {f"GET {A_URL}/leaderboards": "<html>redesigned</html>"})
    failures = check_headroom(ctx)
    assert set(failures) == {A, B} and "no leaderboard table" in failures[A]
    assert ctx.challenges.exists(C) and not ctx.challenges.exists(A) and not ctx.challenges.exists(B)


def test_active_or_unknown_ids_are_clean_errors(env):
    ctx, _ = context(env, [])
    with pytest.raises(RqdError, match="not a finished challenge"):
        check_headroom(ctx, [item_id_for("https://www.aicrowd.com/challenges/active")])


def test_investigate_refuses_solved_before_any_spend_unless_forced(env):
    ctx, _ = context(env, [], pages=SOLVED_PAGES)
    check_headroom(ctx, [A])
    assert ctx.challenges.load(A)["headroom"]["verdict"] == "solved"
    ctx2, runner2 = context(env, [session(investigate_output(), n_search=4)], pages=SOLVED_PAGES)
    with pytest.raises(RqdError, match="solved"):
        investigate(ctx2, [A])
    assert runner2.calls == []
    assert investigate(ctx2, [A], force=True) == {}


def test_investigate_scrapes_headroom_first_and_filters_unbacked_content(env):
    ctx, runner = context(env, [session(investigate_output(), n_search=4)])
    assert investigate(ctx, [A]) == {}
    assert len(runner.calls) == 1 and "Team Y" in runner.calls[0]["input"]  # leaderboard rows given to the agent
    inv = ctx.challenges.load(A)["investigation"]
    assert [s["team"] for s in inv["solutions"]] == ["Team X"] and inv["solutions"][0]["score"] == 0.9
    w = inv["warnings"]
    assert any("Team Y" in x for x in w["dropped_solutions"]) and any("Team Z" in x for x in w["dropped_solutions"])
    assert w["unsupported_numbers"] == ["ideas[2].why_it_could_win: 12.5%"]
    assert inv["search"]["sufficient"] is True


def test_solution_score_backed_by_the_scraped_leaderboard(env):
    out = investigate_output()
    out["evidence"][1] = {"title": "Team Y", "url": "https://c.example/y", "kind": "repo",
                          "quote": "Team Y: self-play with a league of past agents"}
    ctx, _ = context(env, [session(out, n_search=4)])
    investigate(ctx, [A])
    inv = ctx.challenges.load(A)["investigation"]
    assert [(s["team"], s["score"]) for s in inv["solutions"]] == [("Team X", 0.9), ("Team Y", 0.88)]
    assert inv["warnings"]["dropped_scores"] == []


def test_numbers_backed_by_the_headroom_check_are_not_flagged(env):
    out = investigate_output(summary="the winner scored 0.9 against a ceiling of 1.0, a baseline of 0.5 and 0.88 in 2nd",
                             ideas=[])
    ctx, _ = context(env, [session(out, n_search=4)])
    investigate(ctx, [A])
    assert ctx.challenges.load(A)["investigation"]["warnings"]["unsupported_numbers"] == []


def test_cli_headroom_list_investigate_show(env, monkeypatch):
    runner = FakeRunner(session(baseline_output()), session(investigate_output(), n_search=4))
    monkeypatch.setattr(cli, "make_agent_client", lambda: ClaudeCodeClient(runner=runner))
    monkeypatch.setattr(cli, "make_fetcher_for", lambda cfg: make_fetcher(PAGES))
    r = CliRunner()
    assert r.invoke(app, ["--root", str(env), "headroom"]).exit_code == 0
    res = r.invoke(app, ["--root", str(env), "list"])
    assert A in res.output and "headroom 20%" in res.output and "not_applicable" in res.output
    assert "0.9 Accuracy" in res.output
    assert r.invoke(app, ["--root", str(env), "investigate", A]).exit_code == 0
    assert "ideas" in r.invoke(app, ["--root", str(env), "show", A]).output


def test_refusal_runs_on_stores_alone_without_a_client(env, tmp_path):
    from challengeinvestigator.run import refusal
    from rqd.records import YamlStore
    ctx, _ = context(env, [], pages=SOLVED_PAGES)
    check_headroom(ctx, [A])
    store, challenges = Store(tmp_path / "SourceScout" / "data" / "scout.db"), YamlStore(env / "challenges")
    assert refusal(store, challenges, B, False) is None
    assert refusal(store, challenges, A, True) is None
    solved = refusal(store, challenges, A, False)
    assert isinstance(solved, RqdError) and "solved" in str(solved) and "--force" in solved.fix
    active = refusal(store, challenges, item_id_for("https://www.aicrowd.com/challenges/active"), False)
    assert "not a finished challenge" in str(active) and "challenges list" in active.fix
