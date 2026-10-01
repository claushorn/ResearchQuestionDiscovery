"""Local-only means only this machine's own pages may drive the app: a foreign Host (DNS rebinding) or a cross-site
state-changing request (CSRF: any website could start a paid Agent Task) is refused with a clean 403 page."""
import pytest
from fastapi.testclient import TestClient

from fe_testing import fake_cli, fe_client, seed
from frontend.app import create_app
from frontend.db import Triage
from rqd.records import YamlStore

SAME = {"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    import frontend.app as app_module
    s = seed(tmp_path)
    fake_cli(tmp_path / "bin")
    monkeypatch.setattr(app_module, "BIN_DIR", tmp_path / "bin")
    return s


def test_foreign_host_is_refused(env):
    client = TestClient(create_app(env["root"]), base_url="http://attacker-rebound.example")
    res = client.get("/problems")
    assert res.status_code == 403 and "prob-a" not in res.text and "Fix:" in res.text and "Traceback" not in res.text
    assert fe_client(env["root"]).get("/problems").status_code == 200
    assert TestClient(create_app(env["root"]), base_url="http://localhost:8765").get("/problems").status_code == 200
    assert TestClient(create_app(env["root"]), base_url="http://127.0.0.1:9999").get("/").status_code == 403


def test_the_served_port_is_the_allowed_one(env):
    client = TestClient(create_app(env["root"], port=9001), base_url="http://127.0.0.1:9001")
    assert client.get("/problems").status_code == 200


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Origin": "null"},
])
def test_cross_site_posts_are_refused(env, tmp_path, headers):
    client = fe_client(env["root"])
    res = client.post("/tasks/start", data={"action": "fit", "ids": ["prob-c"]}, headers=headers, follow_redirects=False)
    assert res.status_code == 403 and "Fix:" in res.text
    res = client.post("/triage/problem/prob-a", data={"status": "shortlist", "note": ""}, headers=headers)
    assert res.status_code == 403
    assert client.post("/confirm", data={"action": "fit", "ids": ["prob-c"]}, headers=headers).status_code == 403
    assert Triage(env["root"] / "data" / "frontend.db").get_all("problem") == {}
    assert not YamlStore(tmp_path / "PersonalFitInvestigator" / "fits").exists("prob-c")
    assert "Agent Task #" not in client.get("/tasks").text


def test_same_origin_forms_and_htmx_keep_working(env):
    client = fe_client(env["root"])
    assert client.post("/triage/problem/prob-a", data={"status": "shortlist", "note": ""}, headers=SAME).status_code == 200
    assert client.post("/triage/problem/prob-b", data={"status": "reject", "note": ""}).status_code == 200  # no headers
    assert client.post("/confirm", data={"action": "fit", "ids": ["prob-c"]},
                       headers={"Origin": "http://localhost:8765", "Sec-Fetch-Site": "same-origin"}).status_code == 200
    res = client.post("/tasks/start", data={"action": "fit", "ids": ["prob-c"]}, headers=SAME, follow_redirects=False)
    assert res.status_code == 303
