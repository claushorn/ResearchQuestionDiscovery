from datetime import datetime, timedelta, timezone

import pytest

from conftest import make_registry
from sourcescout.categories import load_categories
from sourcescout.config import load_config
from sourcescout.errors import ConfigError, RegistryError
from sourcescout.registry import Registry

KINDS = {"page": (), "grants_gov": ("keyword",)}
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def src(**kw):
    base = {"id": "s1", "name": "S1", "category": "tech_blog", "kind": "page", "url": "https://a.example/x"}
    return base | kw


def test_categories_cover_v1_and_future(paths):
    cats = load_categories(paths.categories)
    enabled = {c.id for c in cats.values() if c.enabled}
    assert enabled == {"gov_solicitation", "challenge_platform", "job_board", "investor_thesis",
                       "tech_blog", "conference_workshop"}
    assert "academic_papers" in cats and not cats["academic_papers"].enabled


def test_config_loads_real_file(paths):
    cfg = load_config(paths.config)
    assert cfg.extraction.model == "claude-opus-5-5"
    assert cfg.extraction.token_budget_per_candidate == 500


def test_config_missing_field_is_config_error(paths):
    paths.config.write_text("extraction: {model: x}\n")
    with pytest.raises(ConfigError):
        load_config(paths.config)


@pytest.mark.parametrize("bad, needle", [
    (src(category="nope"), "unknown category"),
    (src(kind="nope"), "unknown kind"),
    (src(kind="grants_gov"), "requires params"),
    (src(params={"title_include": "("}), "invalid regex"),
])
def test_registry_rejects_bad_source(paths, bad, needle):
    with pytest.raises(RegistryError) as e:
        make_registry(paths, [bad], KINDS)
    assert needle in str(e.value) and "s1" in str(e.value)


def test_registry_rejects_duplicate_id(paths):
    with pytest.raises(RegistryError, match="duplicate"):
        make_registry(paths, [src(), src()], KINDS)


def test_registry_save_load_roundtrip(paths):
    reg = make_registry(paths, [src()], KINDS)
    reg.get("s1").yield_.candidates = 3
    reg.save()
    assert "yield:" in paths.registry.read_text()
    again = Registry.load(paths.registry, reg.categories, KINDS)
    assert again.get("s1").yield_.candidates == 3


def test_registry_load_reports_invalid_entry(paths):
    paths.registry.write_text("sources:\n  - id: s1\n    name: S1\n")
    with pytest.raises(RegistryError, match="s1"):
        Registry.load(paths.registry, load_categories(paths.categories), KINDS)


def test_scannable_filters(paths):
    reg = make_registry(paths, [
        src(id="due"),
        src(id="retired", status="retired"),
        src(id="disabled", category="academic_papers"),
        src(id="fresh", last_scanned=(NOW - timedelta(hours=1)).isoformat()),
    ], KINDS)
    assert [s.id for s in reg.scannable(NOW)] == ["due"]
    assert {s.id for s in reg.scannable(NOW, force=True)} == {"due", "fresh"}
    assert [s.id for s in reg.scannable(NOW, source_id="retired")] == ["retired"]
    assert reg.scannable(NOW, tier="A") == []
