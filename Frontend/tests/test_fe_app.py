import shutil

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from fe_testing import make_frontend
from frontend import cli
from frontend.app import create_app

NAV = ["Overview", "Candidates", "Problems", "Opportunities", "Challenges", "Agent Tasks"]


def test_overview_serves_the_nav(tmp_path):
    res = TestClient(create_app(make_frontend(tmp_path))).get("/")
    assert res.status_code == 200
    for label in NAV:
        assert f">{label}</a>" in res.text
    assert 'src="/static/htmx.min.js"' in res.text and 'id="task-panel"' in res.text


def test_cli_binds_to_localhost_only(tmp_path, monkeypatch):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port: calls.update(host=host, port=port))
    res = CliRunner().invoke(cli.app, ["--root", str(make_frontend(tmp_path)), "--port", "9001", "--no-browser"])
    assert res.exit_code == 0, res.output
    assert calls == {"host": "127.0.0.1", "port": 9001}


def test_config_cannot_bind_elsewhere(tmp_path):
    root = make_frontend(tmp_path, host="0.0.0.0")
    res = CliRunner().invoke(cli.app, ["--root", str(root), "--no-browser"])
    assert res.exit_code == 1 and "ERROR:" in res.output and "Fix:" in res.output and "Traceback" not in res.output


def test_missing_stage_directory_is_a_clean_configuration_error_page(tmp_path):
    root = make_frontend(tmp_path)
    shutil.rmtree(tmp_path / "PersonalFitInvestigator")
    res = TestClient(create_app(root), raise_server_exceptions=False).get("/")
    assert res.status_code == 500
    assert "PersonalFitInvestigator" in res.text and "roots.personalfit" in res.text
    assert "Traceback" not in res.text and ">Overview</a>" in res.text
