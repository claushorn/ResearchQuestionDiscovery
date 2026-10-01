import hashlib

import pytest

from fe_testing import fe_client, seed
from frontend import views
from frontend.config import load_config
from frontend.db import Triage


def test_set_clear_and_note_round_trip(tmp_path):
    t = Triage(tmp_path / "frontend.db")
    t.set("problem", "prob-a", "shortlist", "call them")
    t.set("problem", "prob-b", "reject", "")
    t.set("candidate", "prob-a", "reject", "")  # kinds are separate
    assert t.get_many("problem", ["prob-a", "prob-b", "prob-c"]) == {
        "prob-a": {"status": "shortlist", "note": "call them"}, "prob-b": {"status": "reject", "note": ""}}
    t.set("problem", "prob-a", "none", "")
    assert t.get_many("problem", ["prob-a"]) == {}
    t.set("problem", "prob-a", "none", "only a note")
    assert Triage(tmp_path / "frontend.db").get_all("problem")["prob-a"] == {"status": "none", "note": "only a note"}


def test_unknown_status_or_kind_is_refused(tmp_path):
    t = Triage(tmp_path / "frontend.db")
    with pytest.raises(ValueError):
        t.set("problem", "prob-a", "maybe", "")
    with pytest.raises(ValueError):
        t.set("thing", "prob-a", "shortlist", "")


@pytest.fixture
def env(tmp_path):
    s = seed(tmp_path)
    s["roots"] = load_config(s["root"] / "config.yaml").stage_roots(s["root"])
    s["triage"] = Triage(s["root"] / "data" / "frontend.db")
    return s


def test_views_filter_by_triage(env):
    env["triage"].set("problem", "prob-a", "shortlist", "")
    env["triage"].set("problem", "prob-b", "reject", "")
    tri = env["triage"].get_all("problem")
    ids = lambda f: sorted(r["problem_id"] for r in views.problems(env["roots"], f, "sources", 1, 50, tri).rows)
    assert ids({"triage": "shortlist"}) == ["prob-a"]
    assert ids({"triage": "not_rejected"}) == ["prob-a", "prob-c"]
    assert ids({"triage": "untriaged"}) == ["prob-c"]
    rows = views.problems(env["roots"], {}, "sources", 1, 50, tri).rows
    assert {r["problem_id"]: r["triage"]["status"] for r in rows} == {"prob-a": "shortlist", "prob-b": "reject",
                                                                    "prob-c": "none"}
    c0 = env["candidates"][0]
    env["triage"].set("candidate", c0, "shortlist", "")
    rows = views.candidates(env["roots"], {"triage": "shortlist"}, 1, 50, env["triage"].get_all("candidate")).rows
    assert [r["candidate_id"] for r in rows] == [c0]


def _hashes(tmp_path):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tmp_path.rglob("*"))
            if p.is_file() and "Frontend" not in p.parts}


def test_triage_route_returns_the_control_and_leaves_stage_records_untouched(env, tmp_path):
    before = _hashes(tmp_path)
    client = fe_client(env["root"])
    res = client.post("/triage/problem/prob-a", data={"status": "shortlist", "note": "strong fit"})
    assert res.status_code == 200 and 'class="triage"' in res.text and "strong fit" in res.text
    assert "on shortlist" in res.text
    res = client.post("/triage/opportunity/OPP-0001", data={"status": "reject", "note": ""})
    assert res.status_code == 200
    assert env["triage"].get_all("problem") == {"prob-a": {"status": "shortlist", "note": "strong fit"}}
    assert _hashes(tmp_path) == before
    res = client.post("/triage/problem/prob-a", data={"status": "maybe", "note": ""})
    assert res.status_code == 400 and "Traceback" not in res.text
