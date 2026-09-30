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
