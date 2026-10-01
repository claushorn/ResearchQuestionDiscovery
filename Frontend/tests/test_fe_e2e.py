"""End to end: Problems page -> select -> confirm -> Agent Task (a fake `fit` CLI writing a fit record) -> the row
shows the new fit score."""
import re
import time

from fastapi.testclient import TestClient

from fe_testing import fake_cli, seed

FIT_RECORD = ('{"problem_id": i, "revision": 1, "problem_revision": 1, "profile_digest": "d", "advantages": [], '
              '"gaps": [], "personal_advantage": {"score": 6, "confidence": 0.5, "reasoning": "r"}, "warnings": []}')


def row(html: str, pid: str) -> str:
    return re.search(rf'<tr>\s*<td class="sel"><input type="checkbox" name="ids" value="{pid}".*?</tr>', html, re.S).group(0)


def test_select_confirm_run_and_see_the_new_fit(tmp_path, monkeypatch):
    import frontend.app as app_module
    env = seed(tmp_path)
    fake_cli(tmp_path / "bin", "fit", "fit", "fits", FIT_RECORD)
    monkeypatch.setattr(app_module, "BIN_DIR", tmp_path / "bin")
    client = TestClient(app_module.create_app(env["root"]))
    page = client.get("/problems").text
    assert 'value="fit"' in page and "<strong>6</strong>" not in row(page, "prob-c")
    confirm = client.post("/confirm", data={"action": "fit", "ids": ["prob-c"]}).text
    assert "1 item" in confirm and "$1.50" in confirm
    res = client.post("/tasks/start", data={"action": "fit", "ids": ["prob-c"]}, follow_redirects=False)
    tid = res.headers["location"].rsplit("/", 1)[1]
    end = time.monotonic() + 10
    while "running" in client.get("/tasks/panel").text and time.monotonic() < end:
        time.sleep(0.05)
    assert "done" in client.get(f"/tasks/{tid}").text
    assert "<strong>6</strong>" in row(client.get("/problems").text, "prob-c")
