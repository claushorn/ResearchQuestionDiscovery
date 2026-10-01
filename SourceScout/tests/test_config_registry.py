from datetime import datetime, timedelta, timezone

import pytest

from conftest import make_registry
from sourcescout.categories import load_categories
from sourcescout.config import load_config
from rqd.errors import ConfigError
from sourcescout.errors import RegistryError
from sourcescout.registry import Registry, Source

KINDS = {"page": (), "grants_gov": ("keyword",)}
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def src(**kw):
    base = {"id": "s1", "name": "S1", "category": "tech_blog", "kind": "page", "url": "https://a.example/x"}
    return base | kw


def test_categories_cover_v1_and_future(paths):
    cats = load_categories(paths.categories)
    enabled = {c.id for c in cats.values() if c.enabled}
    assert enabled == {"gov_solicitation", "challenge_platform", "job_board", "investor_thesis",
                       "tech_blog", "conference_workshop", "industry_talk"}
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
    assert "yield:" in paths.registry_state.read_text()
    again = Registry.load(paths.registry, reg.categories, KINDS)
    assert again.get("s1").yield_.candidates == 3


CURATED = """sources:
- id: s1
  name: S1
  category: tech_blog
  kind: rss
  url: https://a.example/feed
"""


def _load(paths):
    from sourcescout.adapters import REQUIRED_PARAMS
    return Registry.load(paths.registry, load_categories(paths.categories), REQUIRED_PARAMS)


def test_save_never_writes_the_tracked_registry(paths):
    # the tracked registry.yaml holds curated config only; runtime state and discovered sources live in data/
    paths.registry.write_text(CURATED)
    reg = _load(paths)
    reg.get("s1").yield_.scans = 2
    reg.add(Source(id="d1", name="D1", category="tech_blog", kind="rss", url="https://d.example/feed",
                   status="candidate", provenance="discovered_from:abc"))
    reg.save()
    assert paths.registry.read_text() == CURATED
    again = _load(paths)
    assert again.get("s1").yield_.scans == 2 and again.get("d1").provenance == "discovered_from:abc"
    assert again.get("d1").status == "candidate"


def test_inline_state_is_migrated_with_a_warning(paths, caplog):
    legacy = CURATED + """  status: retired
  last_scanned: '2026-09-30T11:11:25+00:00'
  yield:
    scans: 4
- id: d1
  name: D1
  category: tech_blog
  kind: rss
  url: https://d.example/feed
  status: candidate
  provenance: discovered_from:abc
"""
    paths.registry.write_text(legacy)
    reg = _load(paths)
    assert reg.get("s1").status == "retired" and reg.get("s1").yield_.scans == 4 and reg.get("d1")
    assert "runtime state" in caplog.text and "git checkout" in caplog.text
    reg.save()
    assert paths.registry.read_text() == legacy                     # never rewritten
    paths.registry.write_text(CURATED)                               # the user restores the tracked file
    again = _load(paths)
    assert again.get("s1").status == "retired" and again.get("d1").provenance == "discovered_from:abc"


def test_state_file_wins_over_stale_inline_state(paths):
    paths.registry.write_text(CURATED)
    reg = _load(paths)
    reg.get("s1").yield_.scans = 9
    reg.save()
    paths.registry.write_text(CURATED + "  yield:\n    scans: 1\n")
    assert _load(paths).get("s1").yield_.scans == 9


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


@pytest.mark.parametrize("params, needle", [
    ({"link_selector": "a[href^=/topics/]"}, "invalid CSS selector"),
    ({"link_selector": "a", "link_pattern": "("}, "invalid regex"),
    ({"link_selector": "a", "content_selector": "::bad"}, "invalid CSS selector"),
])
def test_registry_rejects_bad_selector_or_link_pattern(paths, params, needle):
    kinds = KINDS | {"html_list": ("link_selector",)}
    with pytest.raises(RegistryError) as e:
        make_registry(paths, [src(kind="html_list", params=params)], kinds)
    assert needle in str(e.value) and "s1" in str(e.value)


@pytest.mark.parametrize("key", ["finished_link_text", "finished_after_heading"])
def test_registry_validates_new_listing_regexes(paths, key):
    kinds = KINDS | {"html_list": ("link_selector",)}
    with pytest.raises(RegistryError, match=f"invalid regex in {key}"):
        make_registry(paths, [src(kind="html_list", params={"link_selector": "a", key: "("})], kinds)


@pytest.mark.parametrize("old, new", [("skip_link_text", "finished_link_text"), ("stop_at_heading", "finished_after_heading")])
def test_renamed_listing_params_are_a_clean_error(paths, old, new):
    kinds = KINDS | {"html_list": ("link_selector",)}
    with pytest.raises(RegistryError) as e:
        make_registry(paths, [src(kind="html_list", params={"link_selector": "a", old: "x"})], kinds)
    assert old in str(e.value) and new in e.value.fix
