import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from og_testing import ev, fit, novelty, og_output, problem
from opportunitygenerator import cli
from opportunitygenerator.cli import app
from opportunitygenerator.config import OGPaths, load_config
from opportunitygenerator.run import OGContext, generate, stale_inputs
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import RqdError
from rqd.records import YamlStore
from rqd_testing import FakeRunner, agent_result, make_fetcher, stream, tool_use

OG_ROOT = Path(__file__).resolve().parents[1]
PAGES = {"GET https://d.example/futures": "<html><body>We offer free historical futures bars since 2010.</body></html>"}


def session(output=None, n_search=2):
    return stream(*[tool_use("WebSearch", query=f"q{i}") for i in range(n_search)],
                  agent_result(structured_output=output or og_output()))


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "OpportunityGenerator"
    root.mkdir()
    shutil.copy(OG_ROOT / "config.yaml", root / "config.yaml")
    problems = YamlStore(tmp_path / "ProblemExtractor" / "problems")
    fits = YamlStore(tmp_path / "PersonalFitInvestigator" / "fits")
    for pid in ("prob-a", "prob-b", "prob-nofit"):
        problems.save(problem(pid), pid)
    fits.save(fit("prob-a"), "prob-a")
    fits.save(fit("prob-b", score=4), "prob-b")
    YamlStore(tmp_path / "NoveltyInvestigator" / "investigations").save(novelty(), "prob-a")
    YamlStore(tmp_path / "EconomicValueInvestigator" / "assessments").save(ev(), "prob-a")
    return root


def context(root, outputs, pages=PAGES):
    paths = OGPaths(root)
    runner = FakeRunner(*outputs)
    return OGContext.open(paths, load_config(paths.config), ClaudeCodeClient(runner=runner), make_fetcher(pages),
                          run_id="RUN1"), runner


def test_generate_record_and_brief(env):
    ctx, runner = context(env, [session()])
    assert generate(ctx, ["prob-a"]) == {}
    call = runner.calls[0]
    assert "Large funds may already solve this internally." in call["input"] and "systematic funds" in call["input"]
    assert "project_notes.md" in call["input"]
    rec = ctx.stores.opportunities.load("OPP-0001")
    assert rec["problem_id"] == "prob-a" and rec["recommendation"] == "investigate"
    p = rec["opportunity_profile"]
    assert (p["novelty"], p["economic_value"], p["tractability"], p["personal_advantage"]) == (8, 7, 6, 9)
    assert rec["confidence"] == {"novelty": 0.71, "value": 0.63, "tractability": 0.58, "fit": 0.9}
    assert rec["evidence"][0]["verification"] == "verified" and rec["search"]["searches"] == 2
    assert rec["inputs"] == {"problem_revision": 1, "fit_revision": 1, "fit_profile_digest": "d1",
                             "novelty_revision": 1, "ev_revision": 1}
    brief = (ctx.paths.briefs / "OPP-0001.md").read_text()
    assert "WHY CLAUS?" in brief and "[x] Investigate" in brief


def test_fit_is_required_and_checked_before_any_spend(env):
    ctx, runner = context(env, [])
    with pytest.raises(RqdError, match="no fit"):
        generate(ctx, ["prob-a", "prob-nofit"])
    with pytest.raises(RqdError, match="no problem"):
        generate(ctx, ["prob-zz"])
    assert runner.calls == []


def test_low_fit_is_ignored_whatever_the_model_says(env):
    out = og_output(novelty_score=None, economic_value_score=None, next_step="contact")
    ctx, _ = context(env, [session(out)])
    generate(ctx, ["prob-b"])
    rec = ctx.stores.opportunities.load("OPP-0001")
    assert rec["opportunity_profile"]["personal_advantage"] == 4 and rec["recommendation"] == "ignore"
    assert rec["opportunity_profile"]["novelty"] is None and rec["confidence"]["novelty"] is None


def test_rule_violation_fails_that_problem_only(env):
    bad = og_output(novelty_score=None)  # novelty ran (likely_open): a score is required
    ctx, _ = context(env, [session(bad), session(og_output(novelty_score=None, economic_value_score=None))])
    failures = generate(ctx, ["prob-a", "prob-b"])
    assert list(failures) == ["prob-a"] and "novelty" in failures["prob-a"]
    assert ctx.stores.opportunities.load("OPP-0001")["problem_id"] == "prob-b"


def test_unsupported_numbers_are_warned_but_experiment_cost_is_exempt(env):
    out = og_output(thesis="Could add 12.5% to returns; regime shifts degrade policies by 40%.")
    ctx, _ = context(env, [session(out)])
    generate(ctx, ["prob-a"])
    assert ctx.stores.opportunities.load("OPP-0001")["warnings"]["unsupported_numbers"] == ["thesis: 12.5%"]


def test_unsupported_money_amounts_are_warned(env):
    ctx, _ = context(env, [session(og_output(thesis="Funds spend $2bn a year; the market is 80,000,000 USD."))])
    generate(ctx, ["prob-a"])
    assert ctx.stores.opportunities.load("OPP-0001")["warnings"]["unsupported_amounts"] == ["thesis: $2bn"]


def test_regenerate_keeps_the_id_and_stale_inputs(env, tmp_path):
    ctx, _ = context(env, [session(), session()])
    generate(ctx, ["prob-a"])
    assert stale_inputs(ctx.stores, ctx.stores.opportunities.load("OPP-0001")) == []
    YamlStore(tmp_path / "NoveltyInvestigator" / "investigations").save(novelty(revision=2), "prob-a")
    assert stale_inputs(ctx.stores, ctx.stores.opportunities.load("OPP-0001")) == ["novelty"]
    generate(ctx, ["prob-a"])
    rec = ctx.stores.opportunities.load("OPP-0001")
    assert rec["revision"] == 2 and len(rec["history"]) == 1 and not ctx.stores.opportunities.exists("OPP-0002")


def test_cli_generate_list_show(env, monkeypatch):
    runner = FakeRunner(session())
    monkeypatch.setattr(cli, "make_agent_client", lambda: ClaudeCodeClient(runner=runner))
    monkeypatch.setattr(cli, "make_fetcher_for", lambda cfg: make_fetcher(PAGES))
    r = CliRunner()
    res = r.invoke(app, ["--root", str(env), "generate", "prob-a"])
    assert res.exit_code == 0, res.output
    res = r.invoke(app, ["--root", str(env), "list"])
    assert "OPP-0001" in res.output and "investigate" in res.output and "N8 V7 T6 F9" in res.output
    assert "WHY CLAUS?" in r.invoke(app, ["--root", str(env), "show", "OPP-0001", "--brief"]).output
    assert "opportunity_profile" in r.invoke(app, ["--root", str(env), "show", "prob-a"]).output
    res = r.invoke(app, ["--root", str(env), "show", "OPP-0099"])
    assert res.exit_code == 1 and "ERROR:" in res.output


def test_unknown_novelty_status_is_refused_before_spend(env, tmp_path):
    YamlStore(tmp_path / "NoveltyInvestigator" / "investigations").save(novelty(status="open"), "prob-a")
    ctx, runner = context(env, [])
    with pytest.raises(RqdError, match="unknown novelty status 'open'"):
        generate(ctx, ["prob-a"])
    assert runner.calls == []


@pytest.mark.parametrize("where, broken", [
    ("NoveltyInvestigator/investigations", {"problem_id": "prob-a", "revision": 1}),
    ("PersonalFitInvestigator/fits", {"problem_id": "prob-a", "revision": 1, "problem_revision": 1}),
    ("EconomicValueInvestigator/assessments", {"problem_id": "prob-a", "revision": 1, "confidence": 0.5}),
])
def test_malformed_upstream_record_is_a_clean_error_before_spend(env, tmp_path, where, broken):
    YamlStore(tmp_path / where).save(broken, "prob-a")
    ctx, runner = context(env, [])
    with pytest.raises(RqdError, match="malformed") as e:
        generate(ctx, ["prob-a"])
    assert e.value.fix and runner.calls == []


def test_stray_file_in_the_opportunity_store_is_a_clean_error_before_spend(env):
    (env / "opportunities").mkdir(exist_ok=True)
    (env / "opportunities" / "README.yaml").write_text("note: hand-written\n")
    ctx, runner = context(env, [])
    with pytest.raises(RqdError, match="README.yaml"):
        generate(ctx, ["prob-a"])
    assert runner.calls == []


def test_stale_fit_is_refused(env, tmp_path):
    YamlStore(tmp_path / "ProblemExtractor" / "problems").save(problem("prob-a", revision=2), "prob-a")
    ctx, runner = context(env, [])
    with pytest.raises(RqdError, match="stale") as e:
        generate(ctx, ["prob-a"])
    assert "fit assess prob-a" in e.value.fix and runner.calls == []


def test_inferred_fields_and_counterarguments_do_not_back_numbers(env, tmp_path):
    p = problem("prob-a")
    p["current_state"]["known_solution_inferred"] = "reaches 92.5% accuracy"
    YamlStore(tmp_path / "ProblemExtractor" / "problems").save(p, "prob-a")
    n = novelty() | {"strongest_counterargument": "funds capture 3.7% of this alpha"}
    YamlStore(tmp_path / "NoveltyInvestigator" / "investigations").save(n, "prob-a")
    ctx, _ = context(env, [session(og_output(thesis="Beats 92.5%, captures 3.7%, degrades by 40%."))])
    generate(ctx, ["prob-a"])
    assert ctx.stores.opportunities.load("OPP-0001")["warnings"]["unsupported_numbers"] == ["thesis: 92.5%", "thesis: 3.7%"]


def test_derived_records_with_profile_quotes_are_git_ignored():
    import subprocess
    root = Path(__file__).resolve().parents[2]
    for path in ("PersonalFitInvestigator/fits/prob-x.yaml", "OpportunityGenerator/opportunities/OPP-0001.yaml",
                 "OpportunityGenerator/briefs/OPP-0001.md", "personal_profile/cv.pdf"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=root).returncode == 0, path


def test_checks_run_on_stores_alone_without_a_client(env):
    from opportunitygenerator.run import OGStores, load_inputs
    paths = OGPaths(env)
    stores = OGStores.open(paths, load_config(paths.config))
    problem_rec, fit_rec, nov, ev_rec = load_inputs(stores, "prob-a")
    assert problem_rec["problem_id"] == "prob-a" and nov is not None and ev_rec is not None
    with pytest.raises(RqdError, match="no fit for prob-nofit"):
        load_inputs(stores, "prob-nofit")
    ctx, _ = context(env, [session()])
    generate(ctx, ["prob-a"])
    assert stale_inputs(stores, stores.opportunities.load("OPP-0001")) == []
