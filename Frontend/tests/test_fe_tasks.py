import os
import time

import pytest
from fastapi.testclient import TestClient

from challengeinvestigator.run import refusal
from economicvalue.assess import gate
from fe_testing import fake_cli, seed
from frontend.actions import ACTIONS, confirm
from frontend.app import create_app
from frontend.config import load_config
from frontend.tasks import TaskRunner
from opportunitygenerator.config import OGPaths, load_config as og_config
from opportunitygenerator.ids import opp_id_for
from opportunitygenerator.run import OGStores, load_inputs
from rqd.cli import hold_lock
from rqd.errors import RqdError
from rqd.records import YamlStore


@pytest.fixture
def env(tmp_path):
    s = seed(tmp_path)
    s["roots"] = load_config(s["root"] / "config.yaml").stage_roots(s["root"])
    s["bin"] = tmp_path / "bin"
    fake_cli(s["bin"])
    s["runner"] = TaskRunner(s["root"] / "data", s["roots"], bin_dir=s["bin"])
    return s


def wait(runner, task_id, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = runner.status(task_id)
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} still running")


def test_start_runs_the_stage_cli_and_reports_per_item_results(env):
    runner = env["runner"]
    tid = runner.start("fit", ["prob-a", "prob-c"], force=False)
    st = wait(runner, tid)
    assert st["status"] == "done" and st["exit_code"] == 0
    assert st["argv"][1:] == ["--root", str(env["roots"]["personalfit"]), "assess", "prob-a", "prob-c"]
    assert st["argv"][0] == str(env["bin"] / "fit")
    assert [(i["id"], i["state"]) for i in st["items"]] == [("prob-a", "done"), ("prob-c", "done")]
    assert st["items"][0]["result"] == "advantage 7/10, 1 advantages, 0 warnings"
    assert "[fit 2/2] prob-c -> advantage" in st["log"]
    assert YamlStore(env["roots"]["personalfit"] / "fits").load("prob-c")["fake"] is True
    assert runner.list()[0]["id"] == tid and runner.list()[0]["status"] == "done"


def test_failed_items_and_clean_errors_are_parsed(env):
    runner = env["runner"]
    st = wait(runner, runner.start("fit", ["prob-a", "bad-1"], force=False))
    assert st["status"] == "failed" and st["exit_code"] == 1
    assert st["items"][1] == {"id": "bad-1", "state": "failed", "result": "budget exceeded"}
    st = wait(runner, runner.start("fit", ["err-1"], force=False))
    assert st["status"] == "failed" and st["error"] == ("the usage limit is reached", "Wait for the limit to reset")


def test_running_item_shows_as_running_and_cancel_stops_the_process_and_releases_the_lock(env):
    runner = env["runner"]
    tid = runner.start("fit", ["prob-a", "slow-1", "prob-c"], force=False)
    end = time.monotonic() + 10
    while time.monotonic() < end and "slow-1: running" not in runner.status(tid)["log"]:
        time.sleep(0.05)
    st = runner.status(tid)
    assert [(i["id"], i["state"]) for i in st["items"]] == [("prob-a", "done"), ("slow-1", "running")]
    assert runner.busy() is not None
    pid = st["pid"]
    runner.cancel(tid)
    st = wait(runner, tid)
    assert st["status"] == "cancelled"
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    fits = YamlStore(env["roots"]["personalfit"] / "fits")
    assert fits.load("prob-a")["fake"] is True and not fits.exists("slow-1") and not fits.exists("prob-c")
    with hold_lock(env["roots"]["personalfit"]):  # released
        pass
    assert runner.busy() is None


def test_a_held_lock_makes_it_busy_and_start_is_refused(env):
    runner = env["runner"]
    with hold_lock(env["roots"]["economicvalue"]):
        reason = runner.busy()
        assert reason and "EconomicValueInvestigator" in reason and "outside" in reason
        with pytest.raises(RqdError, match="busy"):
            runner.start("fit", ["prob-a"], force=False)
        client = TestClient(create_app(env["root"]))
        html = client.get("/problems").text
        assert "disabled" in html and "outside" in html
        assert "outside the frontend is running on EconomicValueInvestigator" in client.get("/").text
    assert runner.busy() is None


def test_second_start_while_a_task_runs_is_refused(env):
    runner = env["runner"]
    tid = runner.start("fit", ["slow-1"], force=False)
    with pytest.raises(RqdError, match="busy"):
        runner.start("fit", ["prob-a"], force=False)
    assert "Agent Task" in runner.busy()
    runner.cancel(tid)
    wait(runner, tid)


def test_refusals_are_the_stages_own_checks(env):
    roots = env["roots"]
    problems = YamlStore(roots["problemextractor"] / "problems")
    investigations = YamlStore(roots["noveltyinvestigator"] / "investigations")
    c = confirm(roots, "economic_value", ["prob-a", "prob-b", "prob-c"], force=False)
    with pytest.raises(RqdError) as e:
        gate(problems, investigations, "prob-b", False)
    assert c["refused"] == [{"id": "prob-b", "message": str(e.value), "fix": e.value.fix}]
    assert c["runnable"] == ["prob-a", "prob-c"]
    assert confirm(roots, "economic_value", ["prob-b"], force=True)["refused"] == []
    og = OGStores.open(OGPaths(roots["opportunitygenerator"]), og_config(roots["opportunitygenerator"] / "config.yaml"))
    c = confirm(roots, "generate", ["prob-a", "prob-c"], force=False)
    with pytest.raises(RqdError) as e:
        load_inputs(og, "prob-c")
    assert c["refused"] == [{"id": "prob-c", "message": str(e.value), "fix": e.value.fix}]
    load_inputs(og, "prob-a"), opp_id_for(og.opportunities, "prob-a")  # runnable per the stage
    assert c["runnable"] == ["prob-a"]
    checked, unchecked = env["challenges"]
    YamlStore(roots["challengeinvestigator"] / "challenges").save(
        YamlStore(roots["challengeinvestigator"] / "challenges").load(checked)
        | {"headroom": {"verdict": "solved", "normalized_headroom": 0.0}}, checked)
    from sourcescout.store import Store
    err = refusal(Store(roots["sourcescout"] / "data" / "scout.db"),
                  YamlStore(roots["challengeinvestigator"] / "challenges"), checked, False)
    c = confirm(roots, "investigate", [checked, unchecked], force=False)
    assert c["refused"] == [{"id": checked, "message": str(err), "fix": err.fix}] and c["runnable"] == [unchecked]
    c = confirm(roots, "extract", env["candidates"], force=False)
    assert [r["id"] for r in c["refused"]] == env["candidates"][:3] and c["runnable"] == [env["candidates"][3]]
    assert "already processed" in c["refused"][0]["message"]


def test_confirmation_counts_caps_and_worst_case(env):
    c = confirm(env["roots"], "fit", ["prob-a", "prob-c"], force=False)
    assert (c["count"], c["cap_usd"], c["worst_case_usd"]) == (2, 1.5, 3.0)
    assert c["force_option"] is None and c["existing"] == ["prob-a"]
    c = confirm(env["roots"], "economic_value", ["prob-a"], force=False)
    assert c["force_option"] and c["cap_usd"] == 2.0
    c = confirm(env["roots"], "extract", [env["candidates"][3]], force=False)
    assert c["cap_usd"] is None and "token" in c["cap_note"]
    with pytest.raises(RqdError, match="unknown action"):
        confirm(env["roots"], "nope", ["prob-a"], force=False)
    assert set(ACTIONS) == {"extract", "novelty", "economic_value", "fit", "generate", "headroom", "investigate"}


def test_start_runs_only_runnable_ids(env):
    fake_cli(env["bin"], "economicvalue", "ev", "assessments")
    runner = env["runner"]
    st = wait(runner, runner.start("economic_value", ["prob-b", "prob-c"], force=False))
    assert st["argv"][3:] == ["assess", "prob-c"] and st["refused"][0]["id"] == "prob-b"
    with pytest.raises(RqdError, match="nothing to run"):
        runner.start("economic_value", ["prob-b"], force=False)
    st = wait(runner, runner.start("economic_value", ["prob-b"], force=True))
    assert st["argv"][3:] == ["assess", "prob-b", "--force"]


def test_routes_confirm_start_panel_and_agent_tasks_page(env, monkeypatch):
    import frontend.app as app_module
    monkeypatch.setattr(app_module, "BIN_DIR", env["bin"])
    client = TestClient(create_app(env["root"]))
    html = client.post("/confirm", data={"action": "fit", "ids": ["prob-a", "prob-c"]}).text
    assert "2 items" in html and "$1.50" in html and "$3.00" in html and 'action="/tasks/start"' in html
    res = client.post("/tasks/start", data={"action": "fit", "ids": ["prob-a", "prob-c"]}, follow_redirects=False)
    assert res.status_code == 303
    tid = int(res.headers["location"].rsplit("/", 1)[1])
    runner = TaskRunner(env["root"] / "data", env["roots"], bin_dir=env["bin"])
    wait(runner, tid)
    panel = client.get("/tasks/panel").text
    assert f"#{tid}" in panel and "done" in panel
    page = client.get("/tasks").text
    assert "Agent Tasks" in page and f"/tasks/{tid}" in page
    detail = client.get(f"/tasks/{tid}").text
    assert "prob-c" in detail and "advantage 7/10" in detail
    assert "[fit 1/2]" in client.get(f"/tasks/{tid}/log").text
    res = client.post("/confirm", data={"action": "fit"})
    assert res.status_code == 500 and "Select at least one" in res.text


def test_panel_reloads_the_page_when_items_finished_since_the_last_poll(env, monkeypatch):
    import frontend.app as app_module
    monkeypatch.setattr(app_module, "BIN_DIR", env["bin"])
    client = TestClient(create_app(env["root"]))
    res = client.post("/tasks/start", data={"action": "fit", "ids": ["prob-a"]}, follow_redirects=False)
    tid = int(res.headers["location"].rsplit("/", 1)[1])
    wait(TaskRunner(env["root"] / "data", env["roots"], bin_dir=env["bin"]), tid)
    page = {"HX-Current-URL": "http://127.0.0.1:8765/problems?fit_min=7"}
    assert client.get(f"/tasks/panel?tid={tid}&seen=0", headers=page).headers.get("HX-Refresh") == "true"
    assert "HX-Refresh" not in client.get(f"/tasks/panel?tid={tid}&seen=1", headers=page).headers
    confirm_page = {"HX-Current-URL": "http://127.0.0.1:8765/confirm"}
    assert "HX-Refresh" not in client.get(f"/tasks/panel?tid={tid}&seen=0", headers=confirm_page).headers
