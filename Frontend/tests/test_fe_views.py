import time

import pytest

from fe_testing import candidate, problem, seed
from frontend import views
from frontend.config import load_config
from opportunitygenerator.config import OGPaths, load_config as og_config
from opportunitygenerator.run import OGStores, stale_inputs
from personalfit.profile import load_profile
from personalfit.run import is_stale
from rqd.errors import RqdError
from rqd.records import YamlStore


@pytest.fixture
def env(tmp_path):
    s = seed(tmp_path)
    s["roots"] = load_config(s["root"] / "config.yaml").stage_roots(s["root"])
    return s


def test_candidates_link_to_their_problem_and_filter(env):
    t = views.candidates(env["roots"], {}, page=1, page_size=50)
    by_id = {r["candidate_id"]: r for r in t.rows}
    c0, c1, c2, c3 = env["candidates"]
    assert t.total == 4 and t.errors == []
    assert (by_id[c0]["problem_id"], by_id[c0]["decision"]) == ("prob-a", "new")
    assert by_id[c1]["decision"] == "merged" and by_id[c1]["category"] == "tech_blog" and by_id[c1]["tier"] == "C"
    assert by_id[c3]["problem_id"] is None and by_id[c3]["due_passed"] is True and by_id[c0]["due_passed"] is False
    assert by_id[c0]["payment"] == "$100k" and by_id[c0]["statement"] == "Synthetic problem statement 0."
    assert [r["candidate_id"] for r in views.candidates(env["roots"], {"processed": "no"}, 1, 50).rows] == [c3]
    assert [r["candidate_id"] for r in views.candidates(env["roots"], {"category": "tech_blog"}, 1, 50).rows] == [c1]
    assert [r["candidate_id"] for r in views.candidates(env["roots"], {"q": "statement 2"}, 1, 50).rows] == [c2]


def test_problems_show_the_funnel(env):
    t = views.problems(env["roots"], {}, sort="sources", page=1, page_size=50)
    by_id = {r["problem_id"]: r for r in t.rows}
    a, b, c = by_id["prob-a"], by_id["prob-b"], by_id["prob-c"]
    assert [r["problem_id"] for r in t.rows][0] == "prob-a"  # most sources first
    assert (a["n_sources"], a["best_tier"], a["novelty"], a["fit"], a["opp_id"], a["recommendation"]) == \
        (2, "A", "likely_open", 9, "OPP-0001", "investigate")
    assert a["value"] == (1_000_000, 5_000_000) and a["stale"] == [] and a["waiting"] == []
    assert b["novelty"] == "solved" and b["stale"] == ["fit"] and b["waiting"] == ["economic value", "opportunity"]
    assert c["novelty"] is None and c["fit"] is None and c["waiting"] == ["novelty", "economic value", "fit"]


def test_stale_flags_are_the_stages_own_checks(env, tmp_path):
    roots = env["roots"]
    (tmp_path / "personal_profile" / "notes.md").write_text("Changed profile.\n", encoding="utf-8")
    nov = YamlStore(roots["noveltyinvestigator"] / "investigations")
    nov.save(nov.load("prob-a") | {"revision": 2}, "prob-a")
    problems, fits = YamlStore(roots["problemextractor"] / "problems"), YamlStore(roots["personalfit"] / "fits")
    profile = load_profile(tmp_path / "personal_profile", 200_000)
    og = OGStores.open(OGPaths(roots["opportunitygenerator"]), og_config(roots["opportunitygenerator"] / "config.yaml"))
    rows = {r["problem_id"]: r for r in views.problems(roots, {}, "sources", 1, 50).rows}
    for pid in ("prob-a", "prob-b"):
        assert ("fit" in rows[pid]["stale"]) == is_stale(fits.load(pid), problems.load(pid), profile)
    opp_rows = views.opportunities(roots, {}, 1, 50).rows
    assert opp_rows[0]["stale"] == stale_inputs(og, og.opportunities.load("OPP-0001")) == ["novelty"]
    assert "opportunity: novelty" in rows["prob-a"]["stale"]


def test_problems_filters(env):
    ids = lambda f: sorted(r["problem_id"] for r in views.problems(env["roots"], f, "sources", 1, 50).rows)
    assert ids({"has_fit": "yes"}) == ["prob-a", "prob-b"]
    assert ids({"fit_min": "7"}) == ["prob-a"]
    assert ids({"novelty": "likely_open"}) == ["prob-a"]
    assert ids({"stale": "yes"}) == ["prob-b"]
    assert ids({"waiting": "fit"}) == ["prob-c"]
    assert ids({"q": "of prob-b"}) == ["prob-b"]


def test_dossier_in_pipeline_order(env):
    d = views.dossier(env["roots"], "prob-a")
    assert [c["candidate_id"] for c in d["candidates"]] == env["candidates"][:2]
    assert d["candidates"][0]["source"]["url"] == "https://g.example/0"
    assert d["problem"]["problem"]["precise_statement"] == "Precise statement of prob-a."
    assert d["novelty"]["closest_work"][0]["verification"] == "verified"
    assert d["ev"]["evidence"][0]["verification"] == "unverified"
    assert d["fit"]["advantages"][0]["file"] == "notes.md" and d["fit_stale"] is False
    assert d["opportunity"]["id"] == "OPP-0001" and d["opportunity_stale"] == []
    with pytest.raises(RqdError, match="no problem prob-zzz"):
        views.dossier(env["roots"], "prob-zzz")


def test_opportunities_and_brief(env):
    t = views.opportunities(env["roots"], {}, 1, 50)
    assert [(r["id"], r["problem_id"], r["recommendation"], r["scores"]) for r in t.rows] == \
        [("OPP-0001", "prob-a", "investigate", (8, 7, 6, 8))]
    assert views.brief(env["roots"], "OPP-0001").startswith("# Can we solve prob-a?")
    with pytest.raises(RqdError, match="OPP-0009"):
        views.brief(env["roots"], "OPP-0009")


def test_challenges_list_finished_items_with_their_headroom(env):
    checked, unchecked = env["challenges"]
    t = views.challenges(env["roots"], {}, 1, 50)
    by_id = {r["item_id"]: r for r in t.rows}
    assert set(by_id) == {checked, unchecked}
    assert by_id[checked]["verdict"] == "open" and by_id[checked]["headline"] == "open 40%"
    assert by_id[checked]["winner"] == "0.6 Accuracy" and by_id[checked]["investigated"] is False
    assert by_id[unchecked]["verdict"] is None
    assert [r["item_id"] for r in views.challenges(env["roots"], {"checked": "no"}, 1, 50).rows] == [unchecked]
    detail = views.challenge(env["roots"], checked)
    assert detail["item"].title == "Challenge 0" and detail["record"]["headroom"]["verdict"] == "open"
    assert views.challenge(env["roots"], unchecked)["record"] is None


def test_overview_counts_waiting_and_stale(env):
    o = {s["stage"]: s for s in views.overview(env["roots"])["stages"]}
    assert (o["Candidates"]["count"], o["Candidates"]["waiting"]) == (4, 1)
    assert (o["Problems"]["count"], o["Novelty"]["count"], o["Economic value"]["count"]) == (3, 2, 1)
    assert (o["Fit"]["count"], o["Fit"]["stale"]) == (2, 1)
    assert (o["Opportunities"]["count"], o["Opportunities"]["stale"], o["Opportunities"]["waiting"]) == (1, 0, 1)  # prob-b: fit, no opportunity
    assert (o["Challenges"]["count"], o["Challenges"]["waiting"]) == (2, 1)


def test_malformed_records_are_listed_while_the_others_show(env):
    roots = env["roots"]
    (roots["problemextractor"] / "problems" / "prob-bad.yaml").write_text("problem: [unclosed\n", encoding="utf-8")
    YamlStore(roots["problemextractor"] / "problems").save({"problem_id": "prob-nokeys", "revision": 1}, "prob-nokeys")
    (roots["sourcescout"] / "output" / "2026-09" / "cand-bad.yaml").write_text(":\n- [", encoding="utf-8")
    YamlStore(roots["noveltyinvestigator"] / "investigations").save({"problem_id": "prob-c"}, "prob-c")
    t = views.problems(roots, {}, "sources", 1, 50)
    assert sorted(r["problem_id"] for r in t.rows) == ["prob-a", "prob-b", "prob-c"]  # prob-c: novelty unknown
    files = sorted(e[0].rsplit("/", 1)[-1] for e in t.errors)
    assert files == ["prob-bad.yaml", "prob-c.yaml", "prob-nokeys.yaml"]
    assert all(msg and fix for _, msg, fix in t.errors)
    c = views.candidates(roots, {}, 1, 50)
    assert c.total == 4 and [e[0].rsplit("/", 1)[-1] for e in c.errors] == ["cand-bad.yaml"]


def test_600_problems_filter_sort_page_fast(env):
    roots = env["roots"]
    store = YamlStore(roots["problemextractor"] / "problems")
    padding = {f"field_{k}": f"synthetic extracted text {k} " * 6 for k in range(60)}  # ~8 KB/file, as the real store
    for i in range(600):
        cands = [candidate(100 + i * 3 + k, tier="ABCDE"[i % 5]) for k in range(1 + i % 3)]
        rec = problem(f"prob-s{i:04d}", cands, statement=f"Synthetic {'even' if i % 2 == 0 else 'odd'} {i}")
        rec["merge_log"][0]["extracted"] = padding
        store.save(rec, f"prob-s{i:04d}")
    started = time.monotonic()
    t = views.problems(roots, {"q": "even"}, sort="tier", page=2, page_size=50)
    elapsed = time.monotonic() - started
    assert t.total == 300 and t.pages == 6 and t.page == 2 and len(t.rows) == 50
    assert all("even" in r["statement"] for r in t.rows)
    tiers = [r["best_tier"] for r in views.problems(roots, {"q": "even"}, "tier", 1, 1000).rows]
    assert tiers == sorted(tiers)
    assert elapsed < 1.0, f"{elapsed:.2f}s"
