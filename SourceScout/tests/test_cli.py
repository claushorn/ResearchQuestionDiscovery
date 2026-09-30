import yaml
from typer.testing import CliRunner

from sourcescout.cli import app

runner = CliRunner()


def write_registry(paths, sources):
    paths.registry.write_text(yaml.safe_dump({"sources": sources}))


def test_sources_list(paths):
    write_registry(paths, [{"id": "a", "name": "A", "category": "tech_blog", "kind": "rss", "url": "https://a.example/feed"}])
    res = runner.invoke(app, ["--root", str(paths.root), "sources", "list"])
    assert res.exit_code == 0 and "a" in res.output and "tech_blog" in res.output


def test_bad_registry_prints_clean_error(paths):
    write_registry(paths, [{"id": "a", "name": "A", "category": "nope", "kind": "rss", "url": "https://a.example/feed"}])
    res = runner.invoke(app, ["--root", str(paths.root), "sources", "list"])
    assert res.exit_code == 1
    assert "ERROR: source 'a': unknown category 'nope'" in res.output and "Fix:" in res.output
    assert "Traceback" not in res.output


def test_promote_and_retire(paths):
    write_registry(paths, [{"id": "a", "name": "A", "category": "tech_blog", "kind": "rss", "url": "https://a.example/feed",
                            "status": "candidate", "health": {"consecutive_failures": 4}}])
    assert runner.invoke(app, ["--root", str(paths.root), "sources", "promote", "a"]).exit_code == 0
    src = yaml.safe_load(paths.registry.read_text())["sources"][0]
    assert src["status"] == "active" and src["health"]["consecutive_failures"] == 0
    assert runner.invoke(app, ["--root", str(paths.root), "sources", "retire", "a"]).exit_code == 0
    assert yaml.safe_load(paths.registry.read_text())["sources"][0]["status"] == "retired"


def test_report_without_runs(paths):
    res = runner.invoke(app, ["--root", str(paths.root), "report"])
    assert res.exit_code == 1 and "no run reports" in res.output.lower()


def test_env_file_next_to_scout_dir_is_loaded(paths, monkeypatch):
    monkeypatch.delenv("SOURCESCOUT_TEST_VAR", raising=False)
    (paths.root.parent / ".env").write_text("SOURCESCOUT_TEST_VAR=from-dotenv\n")
    assert runner.invoke(app, ["--root", str(paths.root), "sources", "list"]).exit_code == 0
    import os
    assert os.environ.get("SOURCESCOUT_TEST_VAR") == "from-dotenv"


def test_run_saves_report_even_when_extraction_aborts(paths, monkeypatch):
    from sourcescout import cli
    from sourcescout.errors import ExtractionConfigError

    def no_client():
        raise ExtractionConfigError("Your credit balance is too low", fix="Add credits")
    monkeypatch.setattr(cli, "make_client", no_client)
    res = runner.invoke(app, ["--root", str(paths.root), "run", "--sync"])
    assert res.exit_code == 1 and "credit balance" in res.output
    assert list((paths.root / "data" / "runs").glob("*.json"))


def test_extract_retry_failed_flag_exists():
    res = runner.invoke(app, ["extract", "--help"])
    assert "--retry-failed" in res.output
