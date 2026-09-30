# SourceScout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `sourcescout`, a CLI that scans a self-maintaining registry of funded-call, job-board and industry sources, detects new items, and extracts shallow candidate-problem records (≤ 500 output tokens per candidate) with verified verbatim evidence.

**Architecture:** Deterministic Python collection (per-kind adapters → SQLite item store with new/changed detection) feeds a single Claude API extraction path (structured JSON output, validated by Pydantic; sync or Message Batches). Candidates are written as one YAML file each. A deterministic discovery step proposes new registry sources, and lifecycle rules promote or retire them.

**Tech Stack:** Python 3.12, uv, `anthropic` 1.9 (Messages + Batches, `output_config`), `httpx`, `feedparser`, `selectolax`, `pydantic` v2, `pyyaml`, `typer`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-30-sourcescout-design.md`

## Global Constraints

- Run everything with `uv run` (e.g. `uv run pytest`, `uv run sourcescout ...`); add deps with `uv add`.
- Python `>=3.12`; `anthropic>=1.9` (1.x: HTTP layer is `httpx2`; `output_config={"format":..., "effort":...}`; no `temperature`).
- Default model `claude-opus-5-5`, effort `low` — values live ONLY in `SourceScout/config.yaml` (Pydantic config models have no defaults, so there is one source of truth).
- Budget: ≤ 500 output tokens per candidate, measured from `usage.output_tokens`, reported per source; never hidden.
- The Scout does not analyse, score, or estimate value. Prompt and schema enforce shallow extraction.
- No silent fallbacks. External per-source/per-item failures are recorded and reported; deterministic/internal failures raise a `ScoutError` subclass, which the CLI prints as `ERROR: ...` / `Fix: ...` with exit code 1 and no traceback.
- Every evidence quote is verified against the item text; unmatched → `evidence_verified: false` (kept, not dropped).
- Commits: atomic `git add <files> && git commit -m "..."` in ONE shell call; end messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Repo root is `ResearchQuestionDiscovery/` (its own git repo). Package lives at `SourceScout/sourcescout/`, tests at `SourceScout/tests/`.

## Review Focus

1. A hand-edited `registry.yaml` with a typo'd category/kind, missing required param, or broken regex → clean `RegistryError` naming the source id (Task 1 test).
2. Re-running `scan` on unchanged sources → 0 new, 0 changed; feeds whose items are skipped as "known" must not be re-flagged as changed (Tasks 3, 5 tests).
3. The model's quote differs from the source only in curly-vs-straight quotes or whitespace → still verified; a paraphrase → unverified (Task 7 test).
4. The process is killed while waiting on a batch → the next `extract --batch` collects the already-submitted batch instead of resubmitting or losing items (Task 8 test).
5. A single source returning HTTP 500 / robots-disallow / invalid JSON → that source's error is recorded and the other sources are still scanned (Tasks 2, 5 tests).

## File Structure

```
ResearchQuestionDiscovery/
  pyproject.toml                     # uv project; entry point sourcescout
  SourceScout/
    sources.yaml                     # MODIFY: category classes (tier, enabled)
    registry.yaml                    # CREATE: concrete sources (Task 11 seeds)
    config.yaml                      # CREATE: all tunables
    scout_output_schema.yaml         # MODIFY: extended record example
    README.md                        # CREATE: usage
    sourcescout/
      __init__.py
      errors.py        # ScoutError hierarchy, SourceFetchError
      timeutil.py      # utcnow(), iso()
      config.py        # Config models, Paths, load_yaml, load_config
      categories.py    # Category, load_categories
      registry.py      # Source, Registry (load/validate/save/scannable)
      http.py          # Fetcher (robots, throttle, errors), html_to_text
      adapters/
        __init__.py    # KINDS, REQUIRED_PARAMS
        base.py        # RawItem, IsKnown, Kind
        rss.py  jobboards.py  grants_gov.py  webpage.py
      store.py         # SQLite items, canonical_url, item_id_for
      report.py        # RunReport, ScanStat, ExtractStat
      scan.py          # scan(), title_filter()
      lifecycle.py     # apply_lifecycle()
      schema.py        # Pydantic extraction models, api_schema, length_violations
      extract.py       # prompt, build_params, run_extraction (sync + batch), records
      discover.py      # job-board patterns, feed autodiscovery, discover()
      cli.py           # typer app
    tests/
      conftest.py  test_config_registry.py  test_http.py  test_adapters.py
      test_store.py  test_scan_lifecycle.py  test_schema.py  test_extract.py
      test_extract_batch.py  test_discover.py  test_cli.py  test_live.py
```

---

### Task 1: Scaffold, errors, config, categories, registry

**Files:**
- Create: `pyproject.toml`, `SourceScout/config.yaml`, `SourceScout/sourcescout/__init__.py`, `errors.py`, `timeutil.py`, `config.py`, `categories.py`, `registry.py`, `SourceScout/tests/conftest.py`, `SourceScout/tests/test_config_registry.py`
- Modify: `SourceScout/sources.yaml` (replace flat list with categories)

**Interfaces:**
- Produces:
  - `errors.ScoutError(message: str, fix: str = "")` (`.fix`), subclasses `ConfigError`, `RegistryError`, `ExtractionConfigError`; `errors.SourceFetchError(Exception)`.
  - `timeutil.utcnow() -> datetime` (tz-aware UTC), `timeutil.iso(dt) -> str` (seconds precision).
  - `config.Strict` (BaseModel, extra=forbid); `ExtractionCfg(model, effort, max_tokens, token_budget_per_candidate, max_item_chars, batch_poll_seconds)`, `LifecycleCfg(promote_within_scans, max_consecutive_failures, retire_zero_yield_active)`, `HttpCfg(user_agent, timeout_s, min_interval_s_per_host)`, `DiscoveryCfg(max_fetches_per_run, job_title_include, ignore_hosts)`, `Config(extraction, lifecycle, http, discovery)`; `Paths(root)` with `.categories .registry .config .db .runs .output .unmapped`; `DEFAULT_ROOT`; `load_yaml(path, error_cls)`; `load_config(path) -> Config`.
  - `categories.Category(id, tier, description, enabled)`; `load_categories(path) -> dict[str, Category]`.
  - `registry.Health`, `registry.Yield`, `registry.Source` (field `yield_` aliased `yield`; `.due(now)`), `registry.Registry(path, sources, categories, kinds)` with `.load(path, categories, kinds)`, `.add(s)`, `.find(id)`, `.get(id)`, `.scannable(now, *, source_id=None, category=None, tier=None, force=False)`, `.save()`, attrs `.sources .categories .path`. `kinds: dict[str, tuple[str, ...]]` maps kind → required param names.

- [ ] **Step 1: Create the uv project**

`pyproject.toml`:
```toml
[project]
name = "sourcescout"
version = "0.1.0"
description = "Collects newly exposed, paid-for technical problems from funded calls, job boards and industry sources"
requires-python = ">=3.12"
dependencies = []

[project.scripts]
sourcescout = "sourcescout.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["SourceScout/sourcescout"]

[tool.pytest.ini_options]
testpaths = ["SourceScout/tests"]
markers = ["live: hits the real network and the Anthropic API"]
addopts = "-m 'not live'"
```

Run:
```bash
cd /Users/ch2437/code/ResearchQuestionDiscovery
uv python pin 3.12
uv add "anthropic>=1.9" feedparser httpx selectolax pydantic pyyaml typer
uv add --dev pytest httpx2
mkdir -p SourceScout/sourcescout/adapters SourceScout/tests
touch SourceScout/sourcescout/__init__.py
uv run python -c "import anthropic, httpx2; print(anthropic.__version__)"
```
Expected: prints `1.9.0` (or newer 1.x).

- [ ] **Step 2: Replace `SourceScout/sources.yaml` with category classes**

```yaml
# High-level source category classes. SourceScout scans only registry sources
# (registry.yaml) whose category is enabled here. No URLs live in this file.
categories:
  - id: gov_solicitation
    tier: A
    description: Government funding calls stating a problem with a budget (SBIR/STTR, grants.gov, ARPA-H, ARIA, EU calls)
    enabled: true
  - id: challenge_platform
    tier: A
    description: Prize competitions and research challenges sponsored by organisations (Kaggle, DrivenData, AIcrowd, HeroX, Zindi, protein-design competitions)
    enabled: true
  - id: corporate_open_innovation
    tier: A
    description: Corporate open-innovation and tech-scouting calls (NineSigma, yet2, company challenge portals)
    enabled: false
  - id: job_board
    tier: B
    description: Public job boards; research/engineering postings name problems a team is paid to solve
    enabled: true
  - id: investor_thesis
    tier: B
    description: Investor requests-for-startups and thesis posts naming problem areas they will fund
    enabled: true
  - id: sec_filings
    tier: B
    description: 10-K risk factors and earnings-call transcripts disclosing costly operational problems
    enabled: false
  - id: tech_blog
    tier: C
    description: Technical blogs of companies, startups and AI labs (postmortems, lessons learned, open challenges)
    enabled: true
  - id: conference_workshop
    tier: C
    description: Applied-ML workshop calls for papers and industry-track pages listing open problems
    enabled: true
  - id: github_issues
    tier: C
    description: Long-open, high-reaction issues in company-owned repositories
    enabled: false
  - id: academic_papers
    tier: D
    description: Papers (arXiv, conference papers) mined for limitations / future-work statements
    enabled: false
  - id: benchmark_leaderboard
    tier: D
    description: Benchmarks far from saturation, indicating unsolved tasks
    enabled: false
  - id: discussion
    tier: E
    description: Hacker News, practitioner forums and newsletters (mainly for discovering new sources)
    enabled: false
```

- [ ] **Step 3: Create `SourceScout/config.yaml`** (the only place tunables are defined)

```yaml
extraction:
  model: claude-opus-5-5
  effort: low
  max_tokens: 4000                 # hard stop per request
  token_budget_per_candidate: 500  # reported as a violation when exceeded
  max_item_chars: 20000            # items longer than this are truncated and counted
  batch_poll_seconds: 60
lifecycle:
  promote_within_scans: 5          # candidate: promoted on first candidate, retired after this many scans without one
  max_consecutive_failures: 5
  retire_zero_yield_active: 20     # active: retired after this many scans without a candidate
http:
  user_agent: "SourceScout/0.1 (research source monitor)"
  timeout_s: 30
  min_interval_s_per_host: 2.0
discovery:
  max_fetches_per_run: 30
  job_title_include: "(?i)research|scientist|machine learning|\\bml\\b|reinforcement|optimi[sz]ation|protein|decision|applied ai|member of technical staff"
  ignore_hosts: [twitter.com, x.com, linkedin.com, facebook.com, instagram.com, youtube.com, google.com, wikipedia.org, github.com, medium.com, t.co, bit.ly]
```

- [ ] **Step 4: Write the failing tests**

`SourceScout/tests/conftest.py`:
```python
import shutil
from pathlib import Path

import pytest

from sourcescout.categories import load_categories
from sourcescout.config import Paths
from sourcescout.registry import Registry, Source

REPO_SCOUT = Path(__file__).resolve().parents[1]


@pytest.fixture
def paths(tmp_path) -> Paths:
    shutil.copy(REPO_SCOUT / "sources.yaml", tmp_path / "sources.yaml")
    shutil.copy(REPO_SCOUT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "registry.yaml").write_text("sources: []\n")
    return Paths(tmp_path)


def make_registry(paths: Paths, sources: list[dict], kinds: dict | None = None) -> Registry:
    if kinds is None:  # default kinds come from the adapters (Task 3)
        from sourcescout.adapters import REQUIRED_PARAMS
        kinds = REQUIRED_PARAMS
    cats = load_categories(paths.categories)
    return Registry(paths.registry, [Source.model_validate(s) for s in sources], cats, kinds)
```

`SourceScout/tests/test_config_registry.py`:
```python
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
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_config_registry.py -v`
Expected: FAIL / collection error (`ModuleNotFoundError: sourcescout.categories`).

- [ ] **Step 6: Implement**

`SourceScout/sourcescout/errors.py`:
```python
class ScoutError(Exception):
    """Deterministic, operator-fixable failure. The CLI prints message + fix and exits 1."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


class ConfigError(ScoutError):
    pass


class RegistryError(ScoutError):
    pass


class ExtractionConfigError(ScoutError):
    pass


class SourceFetchError(Exception):
    """External failure while fetching one source; recorded and reported, the run continues."""
```

`SourceScout/sourcescout/timeutil.py`:
```python
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")
```

`SourceScout/sourcescout/config.py`:
```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from sourcescout.errors import ConfigError, ScoutError


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractionCfg(Strict):
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    max_tokens: int
    token_budget_per_candidate: int
    max_item_chars: int
    batch_poll_seconds: int


class LifecycleCfg(Strict):
    promote_within_scans: int
    max_consecutive_failures: int
    retire_zero_yield_active: int


class HttpCfg(Strict):
    user_agent: str
    timeout_s: float
    min_interval_s_per_host: float


class DiscoveryCfg(Strict):
    max_fetches_per_run: int
    job_title_include: str
    ignore_hosts: list[str]


class Config(Strict):
    extraction: ExtractionCfg
    lifecycle: LifecycleCfg
    http: HttpCfg
    discovery: DiscoveryCfg


DEFAULT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def categories(self) -> Path:
        return self.root / "sources.yaml"

    @property
    def registry(self) -> Path:
        return self.root / "registry.yaml"

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def db(self) -> Path:
        return self.root / "data" / "scout.db"

    @property
    def runs(self) -> Path:
        return self.root / "data" / "runs"

    @property
    def output(self) -> Path:
        return self.root / "output"

    @property
    def unmapped(self) -> Path:
        return self.root / "discovered_unmapped.yaml"


def load_yaml(path: Path, error_cls: type[ScoutError]) -> object:
    if not path.exists():
        raise error_cls(f"{path} not found", fix=f"Create {path.name} in {path.parent}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise error_cls(f"{path} is not valid YAML: {e}", fix=f"Fix the YAML syntax in {path}") from e


def load_config(path: Path) -> Config:
    data = load_yaml(path, ConfigError)
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
```

`SourceScout/sourcescout/categories.py`:
```python
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from sourcescout.config import Strict, load_yaml
from sourcescout.errors import ConfigError


class Category(Strict):
    id: str
    tier: Literal["A", "B", "C", "D", "E"]
    description: str
    enabled: bool


def load_categories(path: Path) -> dict[str, Category]:
    data = load_yaml(path, ConfigError)
    if not isinstance(data, dict) or not isinstance(data.get("categories"), list):
        raise ConfigError(f"{path}: expected a mapping with a 'categories' list",
                          fix="See the category format documented in SourceScout/README.md")
    try:
        cats = [Category.model_validate(c) for c in data["categories"]]
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
    out: dict[str, Category] = {}
    for c in cats:
        if c.id in out:
            raise ConfigError(f"{path}: duplicate category id {c.id!r}", fix="Category ids must be unique")
        out[c.id] = c
    return out
```

`SourceScout/sourcescout/registry.py`:
```python
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sourcescout.categories import Category
from sourcescout.config import Strict, load_yaml
from sourcescout.errors import RegistryError


class Health(Strict):
    last_ok: str | None = None
    consecutive_failures: int = 0
    last_error: str | None = None


class Yield(Strict):
    scans: int = 0
    items_seen: int = 0
    candidates: int = 0
    scans_since_candidate: int = 0


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: str
    category: str
    kind: str
    url: str
    params: dict[str, Any] = Field(default_factory=dict)
    cadence_hours: float = 24.0
    status: Literal["active", "candidate", "retired"] = "active"
    provenance: str = "seeded"
    last_scanned: str | None = None
    health: Health = Field(default_factory=Health)
    yield_: Yield = Field(default_factory=Yield, alias="yield")

    def due(self, now: datetime) -> bool:
        if self.last_scanned is None:
            return True
        return now - datetime.fromisoformat(self.last_scanned) >= timedelta(hours=self.cadence_hours)


_FIX = "Edit SourceScout/registry.yaml (categories: sources.yaml; kinds: sourcescout/adapters)"


class Registry:
    def __init__(self, path: Path, sources: list[Source], categories: dict[str, Category],
                 kinds: dict[str, tuple[str, ...]]):
        self.path = path
        self.categories = categories
        self.kinds = kinds
        self.sources: list[Source] = []
        for s in sources:
            self.add(s)

    @classmethod
    def load(cls, path: Path, categories: dict[str, Category], kinds: dict[str, tuple[str, ...]]) -> "Registry":
        data = load_yaml(path, RegistryError)
        raw_sources = data.get("sources") if isinstance(data, dict) else None
        if not isinstance(raw_sources, list):
            raise RegistryError(f"{path}: expected a mapping with a 'sources' list", fix=_FIX)
        sources = []
        for i, raw in enumerate(raw_sources):
            try:
                sources.append(Source.model_validate(raw))
            except ValidationError as e:
                sid = raw.get("id", "?") if isinstance(raw, dict) else "?"
                raise RegistryError(f"{path}: source #{i} ({sid}) is invalid:\n{e}", fix=_FIX) from e
        return cls(path, sources, categories, kinds)

    def _validate(self, s: Source) -> None:
        if s.category not in self.categories:
            raise RegistryError(f"source {s.id!r}: unknown category {s.category!r}",
                                fix=f"Use one of {sorted(self.categories)} (defined in sources.yaml)")
        if s.kind not in self.kinds:
            raise RegistryError(f"source {s.id!r}: unknown kind {s.kind!r}", fix=f"Use one of {sorted(self.kinds)}")
        missing = [p for p in self.kinds[s.kind] if p not in s.params]
        if missing:
            raise RegistryError(f"source {s.id!r}: kind {s.kind!r} requires params {missing}", fix=_FIX)
        for key in ("title_include", "title_exclude"):
            if key in s.params:
                try:
                    re.compile(s.params[key])
                except re.error as e:
                    raise RegistryError(f"source {s.id!r}: invalid regex in {key}: {e}", fix=_FIX) from e

    def add(self, s: Source) -> None:
        if self.find(s.id) is not None:
            raise RegistryError(f"duplicate source id {s.id!r}", fix="Source ids must be unique")
        self._validate(s)
        self.sources.append(s)

    def find(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def get(self, source_id: str) -> Source:
        s = self.find(source_id)
        if s is None:
            raise RegistryError(f"no source {source_id!r}", fix="See `uv run sourcescout sources list`")
        return s

    def scannable(self, now: datetime, *, source_id: str | None = None, category: str | None = None,
                  tier: str | None = None, force: bool = False) -> list[Source]:
        if source_id:
            return [self.get(source_id)]
        out = []
        for s in self.sources:
            cat = self.categories[s.category]
            if s.status == "retired" or not cat.enabled:
                continue
            if (category and s.category != category) or (tier and cat.tier != tier):
                continue
            if not force and not s.due(now):
                continue
            out.append(s)
        return out

    def save(self) -> None:
        data = {"sources": [s.model_dump(by_alias=True) for s in self.sources]}
        tmp = self.path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(tmp, self.path)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests/test_config_registry.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .python-version SourceScout/sources.yaml SourceScout/config.yaml SourceScout/sourcescout SourceScout/tests && git commit -m "feat: scaffold sourcescout with config, categories and registry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: HTTP fetcher and HTML-to-text

**Files:**
- Create: `SourceScout/sourcescout/http.py`, `SourceScout/tests/test_http.py`
- Modify: `SourceScout/tests/conftest.py` (add `make_fetcher`)

**Interfaces:**
- Consumes: `HttpCfg`, `SourceFetchError`.
- Produces: `Fetcher(cfg: HttpCfg, client: httpx.Client | None = None, sleep=time.sleep, clock=time.monotonic)` with `.get(url) -> httpx.Response`, `.post_json(url, payload: dict) -> httpx.Response`; `html_to_text(html: str, base_url: str = "") -> tuple[str, list[str]]`.

- [ ] **Step 1: Append `make_fetcher` to `SourceScout/tests/conftest.py`** (and add `import httpx`, `from sourcescout.config import HttpCfg`, `from sourcescout.http import Fetcher` to its imports)

```python
def make_fetcher(routes: dict, robots: str | None = None, sleeps: list | None = None) -> Fetcher:
    """routes: {"GET https://x/y": str | dict | list | httpx.Response | Exception}"""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots) if robots is not None else httpx.Response(404)
        value = routes.get(f"{request.method} {url}")
        if value is None:
            return httpx.Response(404)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        if isinstance(value, (dict, list)):
            return httpx.Response(200, json=value)
        return httpx.Response(200, text=value)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    record = sleeps if sleeps is not None else []
    return Fetcher(HttpCfg(user_agent="test-agent", timeout_s=5, min_interval_s_per_host=0.0),
                   client=client, sleep=record.append)
```

- [ ] **Step 2: Write the failing tests**

`SourceScout/tests/test_http.py`:
```python
import httpx
import pytest

from conftest import make_fetcher
from sourcescout.config import HttpCfg
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher, html_to_text


def test_html_to_text_strips_boilerplate_and_resolves_links():
    html = """<html><head><script>var x=1</script><style>p{}</style></head>
    <body><nav><a href="/menu">Menu</a></nav><h1>Title</h1>
    <p>We  need   better <b>forecasting</b>.</p><a href="/call">Call</a><a href="/call">dup</a>
    <a href="mailto:x@y.z">mail</a><footer>foot</footer></body></html>"""
    text, links = html_to_text(html, "https://org.example/news/1")
    assert "var x" not in text and "Menu" not in text and "foot" not in text
    assert "Title" in text and "forecasting" in text
    assert links == ["https://org.example/call"]


def test_get_ok_and_http_error():
    f = make_fetcher({"GET https://a.example/ok": "hello", "GET https://a.example/boom": httpx.Response(500)})
    assert f.get("https://a.example/ok").text == "hello"
    with pytest.raises(SourceFetchError, match="HTTP 500"):
        f.get("https://a.example/boom")


def test_network_error_becomes_source_fetch_error():
    req = httpx.Request("GET", "https://a.example/x")
    f = make_fetcher({"GET https://a.example/x": httpx.ConnectError("refused", request=req)})
    with pytest.raises(SourceFetchError, match="refused"):
        f.get("https://a.example/x")


def test_robots_disallow():
    f = make_fetcher({"GET https://a.example/private/x": "secret"},
                     robots="User-agent: *\nDisallow: /private/\n")
    with pytest.raises(SourceFetchError, match="robots.txt disallows"):
        f.get("https://a.example/private/x")


def test_robots_server_error_blocks():
    def handler(request):
        return httpx.Response(503)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    f = Fetcher(HttpCfg(user_agent="t", timeout_s=5, min_interval_s_per_host=0), client=client, sleep=lambda s: None)
    with pytest.raises(SourceFetchError, match="robots.txt"):
        f.get("https://a.example/x")


def test_throttle_per_host():
    sleeps: list[float] = []
    def handler(request):
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, text="ok")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    f = Fetcher(HttpCfg(user_agent="t", timeout_s=5, min_interval_s_per_host=2.0),
                client=client, sleep=sleeps.append, clock=lambda: 100.0)
    f.get("https://a.example/1")
    f.get("https://a.example/2")
    assert sleeps and all(s == 2.0 for s in sleeps)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_http.py -v`
Expected: FAIL (`ModuleNotFoundError: sourcescout.http`).

- [ ] **Step 4: Implement `SourceScout/sourcescout/http.py`**

```python
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

from sourcescout.config import HttpCfg
from sourcescout.errors import SourceFetchError

_BOILERPLATE = ("script", "style", "noscript", "nav", "footer", "header", "svg", "form")


def html_to_text(html: str, base_url: str = "") -> tuple[str, list[str]]:
    """Visible text (one line per block, whitespace collapsed) and absolute outbound links."""
    tree = HTMLParser(html)
    for tag in _BOILERPLATE:
        for node in tree.css(tag):
            node.decompose()
    links = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        links.append(urljoin(base_url, href).split("#")[0])
    root = tree.body or tree.root
    raw = root.text(separator="\n") if root is not None else ""
    lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in raw.splitlines())
    return "\n".join(line for line in lines if line), list(dict.fromkeys(links))


class Fetcher:
    """Polite HTTP client: robots.txt (RFC 9309), per-host throttle, errors -> SourceFetchError."""

    def __init__(self, cfg: HttpCfg, client: httpx.Client | None = None, sleep=time.sleep, clock=time.monotonic):
        self._cfg = cfg
        self._client = client or httpx.Client(timeout=cfg.timeout_s, follow_redirects=True)
        self._client.headers["User-Agent"] = cfg.user_agent
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: dict[str, float] = {}

    def get(self, url: str) -> httpx.Response:
        return self._request("GET", url)

    def post_json(self, url: str, payload: dict) -> httpx.Response:
        return self._request("POST", url, json=payload)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        self._check_robots(url)
        self._throttle(urlsplit(url).netloc)
        try:
            resp = self._client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise SourceFetchError(f"{method} {url}: {e}") from e
        if resp.status_code >= 400:
            raise SourceFetchError(f"{method} {url}: HTTP {resp.status_code}")
        return resp

    def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            self._throttle(parts.netloc)
            try:
                resp = self._client.get(base + "/robots.txt")
            except httpx.HTTPError as e:
                raise SourceFetchError(f"robots.txt unreachable for {base}: {e}") from e
            if resp.status_code >= 500:
                raise SourceFetchError(f"robots.txt for {base}: HTTP {resp.status_code} (treated as disallow)")
            if resp.status_code >= 400:
                self._robots[base] = None  # RFC 9309: unavailable robots.txt -> allow
            else:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                self._robots[base] = rp
        rp = self._robots[base]
        if rp is not None and not rp.can_fetch(self._cfg.user_agent, url):
            raise SourceFetchError(f"robots.txt disallows {url}")

    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self._cfg.min_interval_s_per_host - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()
```

Note: with `separator="\n"` inline elements (`<b>`, `<a>`) land on their own lines ("better\nforecasting\n."). Evidence verification (Task 7) normalises this; `html_to_text` stays simple.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add SourceScout/sourcescout/http.py SourceScout/tests/test_http.py SourceScout/tests/conftest.py && git commit -m "feat: polite HTTP fetcher with robots, throttle and html_to_text

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Adapters (rss, greenhouse, lever, ashby, grants_gov, html_list, page)

**Files:**
- Create: `SourceScout/sourcescout/adapters/{__init__,base,rss,jobboards,grants_gov,webpage}.py`, `SourceScout/tests/test_adapters.py`

**Interfaces:**
- Consumes: `Fetcher`, `html_to_text`, `Source`, `SourceFetchError`.
- Produces: `base.RawItem(source_id, url, title, published, text, links: tuple[str, ...] = ())`; `base.IsKnown = Callable[[str], bool]`; `base.Kind(fetch, required_params)`; `adapters.KINDS: dict[str, Kind]`; `adapters.REQUIRED_PARAMS: dict[str, tuple[str, ...]]`. Every fetch fn: `(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]`. Adapters that fetch a detail page per item skip items for which `is_known(url)` is true (so an unchanged item is never re-hashed from different text).

Source params used: `rss`: `max_items` (30), `fetch_full` (false). `html_list`: `link_selector` (required), `link_pattern`, `max_items` (30), `content_selector`. `page`: `content_selector`. `grants_gov`: `keyword` (required), `rows` (50), `opp_statuses` ("forecasted|posted"); its `url` is `https://api.grants.gov/v1/api/search2`. Any kind: `title_include` / `title_exclude` (applied by scan, Task 5).

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_adapters.py`:
```python
import pytest

from conftest import make_fetcher
from sourcescout.adapters import KINDS, REQUIRED_PARAMS
from sourcescout.errors import SourceFetchError
from sourcescout.registry import Source


def S(kind, url, **params):
    return Source(id=f"t-{kind}", name="t", category="tech_blog", kind=kind, url=url, params=params)


never = lambda url: False  # noqa: E731

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Eng</title>
<item><title>Scaling ranking</title><link>https://eng.example/p/1</link>
<description>&lt;p&gt;Our &lt;a href="https://eng.example/data"&gt;dataset&lt;/a&gt; is hard.&lt;/p&gt;</description>
<pubDate>Mon, 28 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>No link</title></item></channel></rss>"""


def test_rss_summary_mode_and_skips_linkless():
    f = make_fetcher({"GET https://eng.example/feed": RSS})
    items = KINDS["rss"].fetch(S("rss", "https://eng.example/feed"), f, never)
    assert len(items) == 1
    it = items[0]
    assert (it.url, it.title) == ("https://eng.example/p/1", "Scaling ranking")
    assert "dataset is hard" in it.text.replace("\n", " ")
    assert it.links == ("https://eng.example/data",)


def test_rss_fetch_full_skips_known():
    f = make_fetcher({"GET https://eng.example/feed": RSS,
                      "GET https://eng.example/p/1": "<html><body><p>Full article body</p></body></html>"})
    src = S("rss", "https://eng.example/feed", fetch_full=True)
    assert "Full article body" in KINDS["rss"].fetch(src, f, never)[0].text
    assert KINDS["rss"].fetch(src, f, lambda u: True) == []


def test_rss_garbage_raises():
    f = make_fetcher({"GET https://eng.example/feed": "<<<not xml"})
    with pytest.raises(SourceFetchError):
        KINDS["rss"].fetch(S("rss", "https://eng.example/feed"), f, never)


def test_greenhouse():
    data = {"jobs": [{"id": 1, "title": "Research Scientist, RL", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
                      "updated_at": "2026-09-01T00:00:00-04:00",
                      "content": "&lt;p&gt;Solve long-horizon planning.&lt;/p&gt;"}]}
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    items = KINDS["greenhouse"].fetch(S("greenhouse", url), make_fetcher({f"GET {url}": data}), never)
    assert items[0].title == "Research Scientist, RL" and items[0].text == "Solve long-horizon planning."


def test_lever():
    data = [{"id": "a", "text": "ML Engineer", "hostedUrl": "https://jobs.lever.co/acme/a", "createdAt": 1786469891368,
             "openingPlain": "Intro", "descriptionPlain": "Build forecasting.",
             "lists": [{"text": "You will", "content": "<li>Beat baselines</li>"}], "additionalPlain": "Benefits"}]
    url = "https://api.lever.co/v0/postings/acme?mode=json"
    it = KINDS["lever"].fetch(S("lever", url), make_fetcher({f"GET {url}": data}), never)[0]
    assert it.url == "https://jobs.lever.co/acme/a" and it.published.startswith("2026-")
    assert "Build forecasting." in it.text and "Beat baselines" in it.text


def test_ashby_skips_unlisted():
    data = {"jobs": [{"id": "1", "title": "RS", "jobUrl": "https://jobs.ashbyhq.com/acme/1", "publishedAt": "2026-03-12T16:38:15+00:00",
                      "descriptionPlain": "Protein design.", "isListed": True},
                     {"id": "2", "title": "Hidden", "jobUrl": "https://jobs.ashbyhq.com/acme/2", "publishedAt": None,
                      "descriptionPlain": "x", "isListed": False}]}
    url = "https://api.ashbyhq.com/posting-api/job-board/acme"
    items = KINDS["ashby"].fetch(S("ashby", url), make_fetcher({f"GET {url}": data}), never)
    assert [i.title for i in items] == ["RS"]


def test_jobboard_bad_shape_raises():
    url = "https://api.ashbyhq.com/posting-api/job-board/acme"
    with pytest.raises(SourceFetchError, match="unexpected response shape"):
        KINDS["ashby"].fetch(S("ashby", url), make_fetcher({f"GET {url}": {"nope": 1}}), never)


def test_grants_gov():
    search = "https://api.grants.gov/v1/api/search2"
    detail = "https://api.grants.gov/v1/api/fetchOpportunity"
    routes = {
        f"POST {search}": {"data": {"oppHits": [{"id": "353936", "number": "24-569", "title": "MFAI",
                                                  "agency": "NSF", "closeDate": "10/09/2026", "oppStatus": "posted"}]}},
        f"POST {detail}": {"data": {"synopsis": {"synopsisDesc": "<p>Foundations of AI are unsolved.</p>",
                                                  "awardCeilingFormatted": "$1,500,000", "estimatedFundingFormatted": "$8,500,000"}}},
    }
    src = S("grants_gov", search, keyword="machine learning")
    it = KINDS["grants_gov"].fetch(src, make_fetcher(routes), never)[0]
    assert it.url == "https://www.grants.gov/search-results-detail/353936"
    assert "Award ceiling: $1,500,000" in it.text and "Foundations of AI are unsolved." in it.text
    assert KINDS["grants_gov"].fetch(src, make_fetcher(routes), lambda u: True) == []


LIST = """<html><body><a href="/topics/1">T1</a><a href="/topics/2">T2</a><a href="/about">About</a></body></html>"""


def test_html_list_follows_selector_and_skips_known():
    routes = {"GET https://sbir.example/topics": LIST,
              "GET https://sbir.example/topics/1": "<html><head><title>Topic 1</title></head><body><main>Need sensors</main></body></html>",
              "GET https://sbir.example/topics/2": "<html><head><title>Topic 2</title></head><body><main>Need RL</main></body></html>"}
    src = S("html_list", "https://sbir.example/topics", link_selector='a[href^="/topics/"]', content_selector="main")
    items = KINDS["html_list"].fetch(src, make_fetcher(routes), lambda u: u.endswith("/2"))
    assert [(i.title, i.text) for i in items] == [("Topic 1", "Need sensors")]


def test_page_content_selector_missing_raises():
    f = make_fetcher({"GET https://yc.example/rfs": "<html><body><p>x</p></body></html>"})
    with pytest.raises(SourceFetchError, match="content_selector"):
        KINDS["page"].fetch(S("page", "https://yc.example/rfs", content_selector="main"), f, never)


def test_required_params_exposed():
    assert REQUIRED_PARAMS["grants_gov"] == ("keyword",)
    assert REQUIRED_PARAMS["html_list"] == ("link_selector",)
    assert set(REQUIRED_PARAMS) == set(KINDS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_adapters.py -v`
Expected: FAIL (`ModuleNotFoundError: sourcescout.adapters`).

- [ ] **Step 3: Implement**

`adapters/base.py`:
```python
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, NamedTuple

if TYPE_CHECKING:
    from sourcescout.http import Fetcher
    from sourcescout.registry import Source


@dataclass(frozen=True)
class RawItem:
    source_id: str
    url: str
    title: str
    published: str | None
    text: str
    links: tuple[str, ...] = ()


IsKnown = Callable[[str], bool]
FetchFn = Callable[["Source", "Fetcher", IsKnown], list[RawItem]]


class Kind(NamedTuple):
    fetch: FetchFn
    required_params: tuple[str, ...] = ()
```

`adapters/jobboards.py`:
```python
import html
from datetime import datetime, timezone

import httpx

from sourcescout.adapters.base import IsKnown, RawItem
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher, html_to_text
from sourcescout.registry import Source


def _json(resp: httpx.Response, url: str):
    try:
        return resp.json()
    except ValueError as e:
        raise SourceFetchError(f"{url}: invalid JSON ({e})") from e


def _shape_error(url: str, e: Exception) -> SourceFetchError:
    return SourceFetchError(f"{url}: unexpected response shape ({e!r})")


def fetch_greenhouse(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    data = _json(http.get(source.url), source.url)
    try:
        items = []
        for j in data["jobs"]:
            text, links = html_to_text(html.unescape(j.get("content") or ""), j["absolute_url"])
            items.append(RawItem(source.id, j["absolute_url"], j["title"], j.get("updated_at"), text, tuple(links)))
        return items
    except (KeyError, TypeError) as e:
        raise _shape_error(source.url, e) from e


def fetch_lever(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    data = _json(http.get(source.url), source.url)
    try:
        items = []
        for j in data:
            parts = [j.get("openingPlain"), j.get("descriptionPlain")]
            for lst in j.get("lists") or []:
                parts.append(f"{lst['text']}\n{html_to_text(lst.get('content') or '')[0]}")
            parts.append(j.get("additionalPlain"))
            created = j.get("createdAt")
            published = datetime.fromtimestamp(int(created) / 1000, timezone.utc).isoformat() if created else None
            items.append(RawItem(source.id, j["hostedUrl"], j["text"], published, "\n\n".join(p for p in parts if p)))
        return items
    except (KeyError, TypeError, ValueError) as e:
        raise _shape_error(source.url, e) from e


def fetch_ashby(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    data = _json(http.get(source.url), source.url)
    try:
        return [RawItem(source.id, j["jobUrl"], j["title"], j.get("publishedAt"), j.get("descriptionPlain") or "")
                for j in data["jobs"] if j.get("isListed", True)]
    except (KeyError, TypeError) as e:
        raise _shape_error(source.url, e) from e
```

`adapters/rss.py`:
```python
import feedparser

from sourcescout.adapters.base import IsKnown, RawItem
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher, html_to_text
from sourcescout.registry import Source


def fetch(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    resp = http.get(source.url)
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise SourceFetchError(f"{source.url}: not a parseable feed ({feed.get('bozo_exception')})")
    fetch_full = bool(source.params.get("fetch_full", False))
    items = []
    for entry in feed.entries[: int(source.params.get("max_items", 30))]:
        url = entry.get("link")
        if not url:
            continue
        if fetch_full:
            if is_known(url):
                continue
            text, links = html_to_text(http.get(url).text, url)
        else:
            body = entry["content"][0].get("value", "") if entry.get("content") else entry.get("summary", "")
            text, links = html_to_text(body, url)
        items.append(RawItem(source.id, url, entry.get("title", ""), entry.get("published") or entry.get("updated"),
                             text, tuple(links)))
    return items
```

`adapters/grants_gov.py`:
```python
from sourcescout.adapters.base import IsKnown, RawItem
from sourcescout.adapters.jobboards import _json, _shape_error
from sourcescout.http import Fetcher, html_to_text
from sourcescout.registry import Source

DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"


def fetch(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    payload = {"keyword": source.params["keyword"],
               "oppStatuses": source.params.get("opp_statuses", "forecasted|posted"),
               "rows": int(source.params.get("rows", 50))}
    data = _json(http.post_json(source.url, payload), source.url)
    try:
        hits = data["data"]["oppHits"]
        items = []
        for h in hits:
            url = f"https://www.grants.gov/search-results-detail/{h['id']}"
            if is_known(url):
                continue
            detail = _json(http.post_json(DETAIL_URL, {"opportunityId": int(h["id"])}), DETAIL_URL)["data"]
            syn = detail.get("synopsis") or {}
            desc, links = html_to_text(syn.get("synopsisDesc") or "", url)
            text = "\n".join([
                f"Title: {h['title']}",
                f"Agency: {h.get('agency', '')}",
                f"Opportunity number: {h.get('number', '')}",
                f"Status: {h.get('oppStatus', '')}",
                f"Close date: {h.get('closeDate') or ''}",
                f"Award ceiling: {syn.get('awardCeilingFormatted') or ''}",
                f"Estimated total funding: {syn.get('estimatedFundingFormatted') or ''}",
                "",
                desc,
            ])
            items.append(RawItem(source.id, url, h["title"], h.get("openDate"), text, tuple(links)))
        return items
    except (KeyError, TypeError, ValueError) as e:
        raise _shape_error(source.url, e) from e
```

`adapters/webpage.py`:
```python
import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from sourcescout.adapters.base import IsKnown, RawItem
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher, html_to_text
from sourcescout.registry import Source


def page_item(source: Source, url: str, html: str) -> RawItem:
    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else url
    selector = source.params.get("content_selector")
    if selector:
        node = tree.css_first(selector)
        if node is None:
            raise SourceFetchError(f"content_selector {selector!r} matched nothing at {url}")
        html = node.html
    text, links = html_to_text(html, url)
    return RawItem(source.id, url, title, None, text, tuple(links))


def fetch_page(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    resp = http.get(source.url)
    return [page_item(source, str(resp.url), resp.text)]


def fetch_list(source: Source, http: Fetcher, is_known: IsKnown) -> list[RawItem]:
    p = source.params
    resp = http.get(source.url)
    urls = []
    for a in HTMLParser(resp.text).css(p["link_selector"]):
        href = a.attributes.get("href")
        if not href:
            continue
        url = urljoin(str(resp.url), href).split("#")[0]
        if p.get("link_pattern") and not re.search(p["link_pattern"], url):
            continue
        urls.append(url)
    items = []
    for url in list(dict.fromkeys(urls))[: int(p.get("max_items", 30))]:
        if is_known(url):
            continue
        items.append(page_item(source, url, http.get(url).text))
    return items
```

`adapters/__init__.py`:
```python
from sourcescout.adapters import grants_gov, jobboards, rss, webpage
from sourcescout.adapters.base import IsKnown, Kind, RawItem

KINDS: dict[str, Kind] = {
    "rss": Kind(rss.fetch),
    "greenhouse": Kind(jobboards.fetch_greenhouse),
    "lever": Kind(jobboards.fetch_lever),
    "ashby": Kind(jobboards.fetch_ashby),
    "grants_gov": Kind(grants_gov.fetch, ("keyword",)),
    "html_list": Kind(webpage.fetch_list, ("link_selector",)),
    "page": Kind(webpage.fetch_page),
}
REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {k: v.required_params for k, v in KINDS.items()}

__all__ = ["KINDS", "REQUIRED_PARAMS", "IsKnown", "Kind", "RawItem"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SourceScout/sourcescout/adapters SourceScout/tests/test_adapters.py && git commit -m "feat: source adapters for rss, job boards, grants.gov and web pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Item store

**Files:**
- Create: `SourceScout/sourcescout/store.py`, `SourceScout/tests/test_store.py`

**Interfaces:**
- Consumes: `RawItem`.
- Produces: `canonical_url(url) -> str`; `item_id_for(url) -> str` (16 hex); `StoredItem(item_id, source_id, url, title, published, text, links: list[str], revision, truncated, extract_status, batch_id)`; `Store(path)` with `.is_known(url) -> bool`, `.upsert(item, now: str, max_chars: int) -> tuple[Literal["new","changed","unchanged"], bool]`, `.pending(limit=None) -> list[StoredItem]`, `.get(item_id) -> StoredItem | None`, `.mark_submitted(item_ids, batch_id)`, `.submitted_batch_ids() -> list[str]`, `.items_in_batch(batch_id) -> dict[str, StoredItem]`, `.mark_done(item_id)`, `.mark_failed(item_id, error)`, `.reset_pending(item_id)`, `.links_first_seen_since(since: str) -> list[tuple[str, str]]` (link, item_id).

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_store.py`:
```python
from sourcescout.adapters.base import RawItem
from sourcescout.store import Store, canonical_url, item_id_for

T0, T1 = "2026-09-30T10:00:00+00:00", "2026-10-01T10:00:00+00:00"


def item(text="body", url="https://a.example/x", links=()):
    return RawItem("s1", url, "Title", None, text, tuple(links))


def test_canonical_url():
    assert canonical_url("HTTPS://A.example/x/?utm_source=z&id=3#frag") == "https://a.example/x?id=3"
    assert item_id_for("https://a.example/x/") == item_id_for("https://a.example/x?utm_medium=m")


def test_new_unchanged_changed(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    assert st.upsert(item(), T0, 1000) == ("new", False)
    assert st.is_known("https://a.example/x")
    assert st.upsert(item(), T1, 1000) == ("unchanged", False)
    st.mark_done(item_id_for("https://a.example/x"))
    assert st.pending() == []
    assert st.upsert(item("new body"), T1, 1000) == ("changed", False)
    [p] = st.pending()
    assert p.revision == 2 and p.text == "new body" and p.extract_status == "pending"


def test_truncation_is_reported_and_hash_stable(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    assert st.upsert(item("x" * 50), T0, 10) == ("new", True)
    assert st.pending()[0].text == "x" * 10
    assert st.upsert(item("x" * 50), T1, 10) == ("unchanged", True)


def test_batch_bookkeeping(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    st.upsert(item(url="https://a.example/1"), T0, 100)
    st.upsert(item(url="https://a.example/2"), T0, 100)
    ids = [i.item_id for i in st.pending()]
    st.mark_submitted(ids, "batch-1")
    assert st.pending() == [] and st.submitted_batch_ids() == ["batch-1"]
    assert set(st.items_in_batch("batch-1")) == set(ids)
    st.mark_failed(ids[0], "boom")
    st.reset_pending(ids[1])
    assert [i.item_id for i in st.pending()] == [ids[1]]
    assert st.get(ids[0]).extract_status == "failed"


def test_links_first_seen_since(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    st.upsert(item(url="https://a.example/1", links=["https://jobs.lever.co/acme"]), T0, 100)
    st.upsert(item(url="https://a.example/2", links=["https://b.example"]), T1, 100)
    assert [l for l, _ in st.links_first_seen_since(T1)] == ["https://b.example"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError: sourcescout.store`).

- [ ] **Step 3: Implement `SourceScout/sourcescout/store.py`**

```python
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sourcescout.adapters.base import RawItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  item_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  published TEXT,
  content_hash TEXT NOT NULL,
  text TEXT NOT NULL,
  links TEXT NOT NULL,
  truncated INTEGER NOT NULL,
  revision INTEGER NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  extract_status TEXT NOT NULL,   -- pending | submitted | done | failed
  extract_error TEXT,
  batch_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(extract_status);
"""

UpsertResult = Literal["new", "changed", "unchanged"]


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_")])
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", query, ""))


def item_id_for(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class StoredItem:
    item_id: str
    source_id: str
    url: str
    title: str
    published: str | None
    text: str
    links: list[str]
    revision: int
    truncated: bool
    extract_status: str
    batch_id: str | None


def _row(r: sqlite3.Row) -> StoredItem:
    return StoredItem(r["item_id"], r["source_id"], r["url"], r["title"], r["published"], r["text"],
                      json.loads(r["links"]), r["revision"], bool(r["truncated"]), r["extract_status"], r["batch_id"])


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def is_known(self, url: str) -> bool:
        return self._db.execute("SELECT 1 FROM items WHERE item_id=?", (item_id_for(url),)).fetchone() is not None

    def upsert(self, item: RawItem, now: str, max_chars: int) -> tuple[UpsertResult, bool]:
        truncated = len(item.text) > max_chars
        text = item.text[:max_chars]
        digest = hashlib.sha256(text.encode()).hexdigest()
        iid = item_id_for(item.url)
        row = self._db.execute("SELECT content_hash FROM items WHERE item_id=?", (iid,)).fetchone()
        links = json.dumps(list(item.links))
        with self._db:
            if row is None:
                self._db.execute(
                    "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,1,?,?,'pending',NULL,NULL)",
                    (iid, item.source_id, item.url, item.title, item.published, digest, text, links,
                     int(truncated), now, now))
                return "new", truncated
            if row["content_hash"] != digest:
                self._db.execute(
                    "UPDATE items SET title=?, published=?, content_hash=?, text=?, links=?, truncated=?, "
                    "revision=revision+1, last_seen=?, extract_status='pending', extract_error=NULL, batch_id=NULL "
                    "WHERE item_id=?",
                    (item.title, item.published, digest, text, links, int(truncated), now, iid))
                return "changed", truncated
            self._db.execute("UPDATE items SET last_seen=? WHERE item_id=?", (now, iid))
            return "unchanged", truncated

    def pending(self, limit: int | None = None) -> list[StoredItem]:
        rows = self._db.execute(
            "SELECT * FROM items WHERE extract_status='pending' ORDER BY first_seen, item_id LIMIT ?",
            (-1 if limit is None else limit,))
        return [_row(r) for r in rows]

    def get(self, item_id: str) -> StoredItem | None:
        r = self._db.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone()
        return _row(r) if r else None

    def mark_submitted(self, item_ids: list[str], batch_id: str) -> None:
        with self._db:
            self._db.executemany("UPDATE items SET extract_status='submitted', batch_id=? WHERE item_id=?",
                                 [(batch_id, i) for i in item_ids])

    def submitted_batch_ids(self) -> list[str]:
        rows = self._db.execute("SELECT DISTINCT batch_id FROM items WHERE extract_status='submitted' ORDER BY batch_id")
        return [r["batch_id"] for r in rows]

    def items_in_batch(self, batch_id: str) -> dict[str, StoredItem]:
        rows = self._db.execute("SELECT * FROM items WHERE extract_status='submitted' AND batch_id=?", (batch_id,))
        return {r["item_id"]: _row(r) for r in rows}

    def _set(self, item_id: str, status: str, error: str | None) -> None:
        with self._db:
            self._db.execute("UPDATE items SET extract_status=?, extract_error=?, batch_id=NULL WHERE item_id=?",
                             (status, error, item_id))

    def mark_done(self, item_id: str) -> None:
        self._set(item_id, "done", None)

    def mark_failed(self, item_id: str, error: str) -> None:
        self._set(item_id, "failed", error)

    def reset_pending(self, item_id: str) -> None:
        self._set(item_id, "pending", None)

    def links_first_seen_since(self, since: str) -> list[tuple[str, str]]:
        rows = self._db.execute("SELECT item_id, links FROM items WHERE first_seen >= ?", (since,))
        return [(link, r["item_id"]) for r in rows for link in json.loads(r["links"])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SourceScout/sourcescout/store.py SourceScout/tests/test_store.py && git commit -m "feat: SQLite item store with new/changed detection and batch bookkeeping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Run report, scan, lifecycle

**Files:**
- Create: `SourceScout/sourcescout/report.py`, `scan.py`, `lifecycle.py`, `SourceScout/tests/test_scan_lifecycle.py`

**Interfaces:**
- Consumes: `Registry`, `Source`, `Health`, `Store`, `Fetcher`, `KINDS`, `SourceFetchError`, `LifecycleCfg`, `iso`.
- Produces:
  - `report.ScanStat(new, changed, unchanged, filtered, truncated, error)`, `report.ExtractStat(items, failed, candidates, output_tokens, input_tokens, cache_read_tokens, unverified, length_violations)` with `.tokens_per_candidate() -> float | None`; `report.RunReport(run_id, started, scan, extract, failures, lifecycle, discovered, unmapped, discovery_errors)` with `.new(now)`, `.scan_stat(id)`, `.extract_stat(id)`, `.budget_violations(budget) -> dict[str, float]` (key `"ALL"` for the run total), `.save(runs_dir) -> Path`, `.load(path)`, `.latest(runs_dir) -> Path | None`, `.render(budget) -> str`.
  - `scan.title_filter(source, items) -> tuple[list[RawItem], int]`; `scan.scan(registry, store, http, report, *, now, max_item_chars, source_id=None, category=None, tier=None, force=False) -> None` (saves registry).
  - `lifecycle.apply_lifecycle(registry, cfg: LifecycleCfg) -> list[str]` (does not save).

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_scan_lifecycle.py`:
```python
from datetime import datetime, timezone

import httpx

from conftest import make_fetcher, make_registry
from sourcescout.config import LifecycleCfg
from sourcescout.lifecycle import apply_lifecycle
from sourcescout.report import ExtractStat, RunReport
from sourcescout.scan import scan
from sourcescout.store import Store

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
PAGE = "<html><head><title>{t}</title></head><body><p>{b}</p></body></html>"


def page_src(id, url, **params):
    return {"id": id, "name": id, "category": "tech_blog", "kind": "page", "url": url, "params": params}


def run_scan(reg, store, routes, **kw):
    report = RunReport.new(NOW)
    scan(reg, store, make_fetcher(routes), report, now=NOW, max_item_chars=1000, force=True, **kw)
    return report


def test_scan_new_unchanged_changed_and_failure_isolated(paths):
    reg = make_registry(paths, [page_src("ok", "https://a.example/p"), page_src("bad", "https://b.example/p")])
    store = Store(paths.db)
    routes = {"GET https://a.example/p": PAGE.format(t="T", b="v1"), "GET https://b.example/p": httpx.Response(500)}
    r1 = run_scan(reg, store, routes)
    assert r1.scan["ok"].new == 1 and "HTTP 500" in r1.scan["bad"].error
    assert reg.get("bad").health.consecutive_failures == 1
    assert reg.get("ok").yield_.scans == 1 and reg.get("ok").health.last_ok
    assert run_scan(reg, store, routes).scan["ok"].unchanged == 1
    routes["GET https://a.example/p"] = PAGE.format(t="T", b="v2")
    assert run_scan(reg, store, routes).scan["ok"].changed == 1
    assert "consecutive_failures: 3" in paths.registry.read_text()


def test_title_filter(paths):
    reg = make_registry(paths, [page_src("f", "https://a.example/p", title_exclude="(?i)sales")])
    report = run_scan(reg, Store(paths.db), {"GET https://a.example/p": PAGE.format(t="Sales Lead", b="x")})
    assert report.scan["f"].filtered == 1 and report.scan["f"].new == 0


def test_lifecycle_rules(paths):
    reg = make_registry(paths, [
        page_src("cand_hit", "https://a.example/1") | {"status": "candidate", "yield": {"scans": 2, "candidates": 1}},
        page_src("cand_miss", "https://a.example/2") | {"status": "candidate", "yield": {"scans": 5}},
        page_src("act_dry", "https://a.example/3") | {"yield": {"scans": 30, "scans_since_candidate": 20}},
        page_src("act_broken", "https://a.example/4") | {"health": {"consecutive_failures": 5, "last_error": "HTTP 404"}},
        page_src("act_fine", "https://a.example/5") | {"yield": {"scans": 30, "scans_since_candidate": 3}},
    ])
    msgs = apply_lifecycle(reg, LifecycleCfg(promote_within_scans=5, max_consecutive_failures=5, retire_zero_yield_active=20))
    status = {s.id: s.status for s in reg.sources}
    assert status == {"cand_hit": "active", "cand_miss": "retired", "act_dry": "retired",
                      "act_broken": "retired", "act_fine": "active"}
    assert len(msgs) == 4 and any("HTTP 404" in m for m in msgs)


def test_report_budget_and_roundtrip(paths):
    r = RunReport.new(NOW)
    r.extract["a"] = ExtractStat(items=2, candidates=2, output_tokens=1400)
    r.extract["b"] = ExtractStat(items=3, candidates=3, output_tokens=1100)
    r.extract["c"] = ExtractStat(items=1, candidates=0, output_tokens=200)
    v = r.budget_violations(500)
    assert v == {"a": 700.0, "ALL": 540.0}  # (1400+1100+200)/5
    path = r.save(paths.runs)
    again = RunReport.load(path)
    assert again.extract["a"].output_tokens == 1400 and RunReport.latest(paths.runs) == path
    text = again.render(500)
    assert "BUDGET VIOLATIONS" in text and "a" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_scan_lifecycle.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`SourceScout/sourcescout/report.py`:
```python
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from sourcescout.timeutil import iso


@dataclass
class ScanStat:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    filtered: int = 0
    truncated: int = 0
    error: str | None = None


@dataclass
class ExtractStat:
    items: int = 0
    failed: int = 0
    candidates: int = 0
    output_tokens: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    unverified: int = 0
    length_violations: int = 0

    def tokens_per_candidate(self) -> float | None:
        return self.output_tokens / self.candidates if self.candidates else None


@dataclass
class RunReport:
    run_id: str
    started: str
    scan: dict[str, ScanStat] = field(default_factory=dict)
    extract: dict[str, ExtractStat] = field(default_factory=dict)
    failures: list[dict[str, str]] = field(default_factory=list)
    lifecycle: list[str] = field(default_factory=list)
    discovered: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    discovery_errors: list[str] = field(default_factory=list)

    @classmethod
    def new(cls, now: datetime) -> "RunReport":
        return cls(run_id=now.strftime("%Y%m%dT%H%M%SZ"), started=iso(now))

    def scan_stat(self, source_id: str) -> ScanStat:
        return self.scan.setdefault(source_id, ScanStat())

    def extract_stat(self, source_id: str) -> ExtractStat:
        return self.extract.setdefault(source_id, ExtractStat())

    def budget_violations(self, budget: int) -> dict[str, float]:
        out = {sid: tpc for sid, st in self.extract.items()
               if (tpc := st.tokens_per_candidate()) is not None and tpc > budget}
        cands = sum(st.candidates for st in self.extract.values())
        if cands:
            total = sum(st.output_tokens for st in self.extract.values()) / cands
            if total > budget:
                out["ALL"] = total
        return out

    def save(self, runs_dir: Path) -> Path:
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{self.run_id}.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "RunReport":
        d = json.loads(path.read_text(encoding="utf-8"))
        d["scan"] = {k: ScanStat(**v) for k, v in d["scan"].items()}
        d["extract"] = {k: ExtractStat(**v) for k, v in d["extract"].items()}
        return cls(**d)

    @staticmethod
    def latest(runs_dir: Path) -> Path | None:
        runs = sorted(runs_dir.glob("*.json")) if runs_dir.exists() else []
        return runs[-1] if runs else None

    def render(self, budget: int) -> str:
        lines = [f"Run {self.run_id} (started {self.started})", "", "SCAN"]
        lines.append(f"  {'source':32} {'new':>4} {'chg':>4} {'same':>5} {'filt':>5} {'trunc':>5}  error")
        for sid, s in sorted(self.scan.items()):
            lines.append(f"  {sid:32} {s.new:>4} {s.changed:>4} {s.unchanged:>5} {s.filtered:>5} {s.truncated:>5}  {s.error or ''}")
        lines += ["", "EXTRACT"]
        lines.append(f"  {'source':32} {'items':>5} {'fail':>4} {'cand':>4} {'out_tok':>8} {'tok/cand':>8} {'cache_rd':>8} {'unverif':>7} {'len_viol':>8}")
        for sid, e in sorted(self.extract.items()):
            tpc = e.tokens_per_candidate()
            lines.append(f"  {sid:32} {e.items:>5} {e.failed:>4} {e.candidates:>4} {e.output_tokens:>8} "
                         f"{(f'{tpc:.0f}' if tpc is not None else 'n/a'):>8} {e.cache_read_tokens:>8} {e.unverified:>7} {e.length_violations:>8}")
        violations = self.budget_violations(budget)
        lines += ["", f"BUDGET VIOLATIONS (> {budget} output tokens/candidate): "
                  + (", ".join(f"{k}={v:.0f}" for k, v in violations.items()) or "none")]
        for title, entries in [("ITEM FAILURES", [f"{f['source_id']}/{f['item_id']}: {f['error']}" for f in self.failures]),
                               ("LIFECYCLE", self.lifecycle), ("DISCOVERED", self.discovered),
                               ("UNMAPPED (review discovered_unmapped.yaml)", self.unmapped),
                               ("DISCOVERY ERRORS", self.discovery_errors)]:
            lines += ["", f"{title}: {len(entries)}"] + [f"  {x}" for x in entries]
        return "\n".join(lines)
```

`SourceScout/sourcescout/scan.py`:
```python
import re
from datetime import datetime

from sourcescout.adapters import KINDS, RawItem
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher
from sourcescout.registry import Health, Registry, Source
from sourcescout.report import RunReport
from sourcescout.store import Store
from sourcescout.timeutil import iso


def title_filter(source: Source, items: list[RawItem]) -> tuple[list[RawItem], int]:
    inc = source.params.get("title_include")
    exc = source.params.get("title_exclude")
    kept = [i for i in items
            if (not inc or re.search(inc, i.title)) and not (exc and re.search(exc, i.title))]
    return kept, len(items) - len(kept)


def scan(registry: Registry, store: Store, http: Fetcher, report: RunReport, *, now: datetime,
         max_item_chars: int, source_id: str | None = None, category: str | None = None,
         tier: str | None = None, force: bool = False) -> None:
    now_s = iso(now)
    for source in registry.scannable(now, source_id=source_id, category=category, tier=tier, force=force):
        stat = report.scan_stat(source.id)
        try:
            items = KINDS[source.kind].fetch(source, http, store.is_known)
        except SourceFetchError as e:
            stat.error = str(e)
            source.health.consecutive_failures += 1
            source.health.last_error = str(e)
            continue
        items, stat.filtered = title_filter(source, items)
        for item in items:
            status, truncated = store.upsert(item, now_s, max_item_chars)
            setattr(stat, status, getattr(stat, status) + 1)
            stat.truncated += int(truncated)
        source.health = Health(last_ok=now_s)
        source.last_scanned = now_s
        source.yield_.scans += 1
        source.yield_.items_seen += len(items)
        source.yield_.scans_since_candidate += 1
    registry.save()
```

`SourceScout/sourcescout/lifecycle.py`:
```python
from sourcescout.config import LifecycleCfg
from sourcescout.registry import Registry


def apply_lifecycle(registry: Registry, cfg: LifecycleCfg) -> list[str]:
    """Promote/retire sources by the spec §3.7 rules. Returns one message per transition."""
    msgs = []
    for s in registry.sources:
        if s.status == "retired":
            continue
        reason = None
        if s.health.consecutive_failures >= cfg.max_consecutive_failures:
            reason = f"{s.health.consecutive_failures} consecutive failures (last: {s.health.last_error})"
        elif s.status == "candidate" and s.yield_.candidates > 0:
            s.status = "active"
            msgs.append(f"{s.id}: candidate -> active (first candidate after {s.yield_.scans} scans)")
        elif s.status == "candidate" and s.yield_.scans >= cfg.promote_within_scans:
            reason = f"no candidate in first {s.yield_.scans} scans"
        elif s.status == "active" and s.yield_.scans_since_candidate >= cfg.retire_zero_yield_active:
            reason = f"no candidate in last {s.yield_.scans_since_candidate} scans"
        if reason:
            msgs.append(f"{s.id}: {s.status} -> retired ({reason})")
            s.status = "retired"
    return msgs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SourceScout/sourcescout/report.py SourceScout/sourcescout/scan.py SourceScout/sourcescout/lifecycle.py SourceScout/tests/test_scan_lifecycle.py && git commit -m "feat: scan orchestration, run report and source lifecycle rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Extraction schema

**Files:**
- Create: `SourceScout/sourcescout/schema.py`, `SourceScout/tests/test_schema.py`
- Modify: `SourceScout/scout_output_schema.yaml` (replace with the extended example below)

**Interfaces:**
- Produces: `MAX_CANDIDATES = 3`; `WORD_LIMITS: dict[str, int]`; Pydantic models `UnsolvedSignal(present, evidence)`, `PaymentSignal(type, stated, evidence, deadline)`, `Entities(organizations, researchers)`, `ExtractedCandidate(statement, why_interesting, explicit_unsolved_signal, payment_signal, technical_area, entities, referenced_urls)`, `ExtractionResult(candidates)`; `api_schema(model: type[BaseModel]) -> dict`; `EXTRACTION_SCHEMA = api_schema(ExtractionResult)`; `length_violations(c: ExtractedCandidate) -> list[str]`.

Why word limits are not in the API schema: structured outputs do not support `maxLength`/`maxItems`; hard caps (≤ 3 candidates, ≤ 3 technical areas) are enforced by Pydantic on the client, word limits are instructed in the prompt and **reported** per candidate (`length_violations`) rather than failing the item.

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_schema.py`:
```python
import pytest
from pydantic import BaseModel, Field, ValidationError

from sourcescout.schema import EXTRACTION_SCHEMA, ExtractionResult, api_schema, length_violations

FORBIDDEN = {"maxLength", "minLength", "maxItems", "minItems", "title", "default"}


def walk(node):
    if isinstance(node, dict):
        yield node
        for k, v in node.items():
            if k in ("properties", "$defs"):
                for sub in v.values():
                    yield from walk(sub)
            else:
                yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def test_api_schema_is_structured_output_compatible():
    for node in walk(EXTRACTION_SCHEMA):
        assert not (FORBIDDEN & node.keys()), node
        if node.get("type") == "object":
            assert node["additionalProperties"] is False


def test_sanitizer_keeps_property_named_title():
    class M(BaseModel):
        title: str = Field(default="x", max_length=5)
    s = api_schema(M)
    assert "title" in s["properties"] and s["additionalProperties"] is False
    assert "default" not in s["properties"]["title"]


def cand(**kw):
    base = {"statement": "Forecast grid load under extreme weather.", "why_interesting": "Utility says outages cost millions.",
            "explicit_unsolved_signal": {"present": True, "evidence": "remains an open challenge"},
            "payment_signal": {"type": "grant", "stated": "$1.5M", "evidence": "up to $1.5M", "deadline": None},
            "technical_area": ["forecasting"], "entities": {"organizations": ["DOE"], "researchers": []},
            "referenced_urls": []}
    return base | kw


def test_max_three_candidates():
    ExtractionResult.model_validate({"candidates": [cand()] * 3})
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"candidates": [cand()] * 4})


def test_length_violations():
    c = ExtractionResult.model_validate({"candidates": [cand(statement="word " * 61)]}).candidates[0]
    assert length_violations(c) == ["statement"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_schema.py -v`
Expected: FAIL (`ModuleNotFoundError: sourcescout.schema`).

- [ ] **Step 3: Implement `SourceScout/sourcescout/schema.py`**

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CANDIDATES = 3
WORD_LIMITS = {"statement": 60, "why_interesting": 30,
               "explicit_unsolved_signal.evidence": 50, "payment_signal.evidence": 50}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UnsolvedSignal(_M):
    present: bool
    evidence: str


class PaymentSignal(_M):
    type: Literal["prize", "grant", "contract", "hiring", "investor_thesis", "none_stated"]
    stated: str
    evidence: str
    deadline: str | None


class Entities(_M):
    organizations: list[str]
    researchers: list[str]


class ExtractedCandidate(_M):
    statement: str
    why_interesting: str
    explicit_unsolved_signal: UnsolvedSignal
    payment_signal: PaymentSignal
    technical_area: list[str] = Field(max_length=3)
    entities: Entities
    referenced_urls: list[str]


class ExtractionResult(_M):
    candidates: list[ExtractedCandidate] = Field(max_length=MAX_CANDIDATES)


_DROP = {"title", "default", "maxLength", "minLength", "maxItems", "minItems"}


def _sanitize(node):
    if isinstance(node, list):
        return [_sanitize(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in _DROP:
            continue
        out[k] = {name: _sanitize(sub) for name, sub in v.items()} if k in ("properties", "$defs") else _sanitize(v)
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


def api_schema(model: type[BaseModel]) -> dict:
    """JSON schema accepted by output_config.format (unsupported constraints removed; Pydantic enforces them)."""
    return _sanitize(model.model_json_schema())


EXTRACTION_SCHEMA = api_schema(ExtractionResult)


def length_violations(c: ExtractedCandidate) -> list[str]:
    values = {"statement": c.statement, "why_interesting": c.why_interesting,
              "explicit_unsolved_signal.evidence": c.explicit_unsolved_signal.evidence,
              "payment_signal.evidence": c.payment_signal.evidence}
    return [k for k, v in values.items() if len(v.split()) > WORD_LIMITS[k]]
```

- [ ] **Step 4: Replace `SourceScout/scout_output_schema.yaml`**

```yaml
# One candidate record per file: SourceScout/output/YYYY-MM/<candidate_id>.yaml
source_id: grants-gov-ml            # registry.yaml id
item_id: 3f2a9c0d1e4b5a6f           # store id (sha256 of canonical URL, 16 hex)
candidate_id: cand-3f2a9c0d1e4b5a6f-r1-0
revision: 1                         # increments when the source item's content changes
source:
  url: ...
  title: ...
  date: ...
  tier: A
  category: gov_solicitation
candidate_problem:
  statement: ...                    # <= 60 words
why_interesting: ...                # one sentence, <= 30 words, stated not analysed
explicit_unsolved_signal:
  present: true
  evidence: "<verbatim quote>"      # <= 50 words
payment_signal:                     # raw, as stated; not scored
  type: grant                       # prize | grant | contract | hiring | investor_thesis | none_stated
  stated: "up to $1.5M"
  evidence: "<verbatim quote>"
  deadline: 2026-12-01              # or null
technical_area: [...]               # <= 3 tags
entities:
  organizations: [...]
  researchers: [...]
referenced_urls: [...]
evidence_verified: true             # every non-empty quote found verbatim in the source text
length_violations: []               # fields exceeding their word limit
extracted_with:
  model: claude-opus-5-5
  run_id: 20260930T120000Z
  output_tokens: 410                # item output tokens / candidates from that item
  at: 2026-09-30T12:00:00+00:00
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add SourceScout/sourcescout/schema.py SourceScout/tests/test_schema.py SourceScout/scout_output_schema.yaml && git commit -m "feat: extraction schema with structured-output sanitizer and length checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Extractor — prompt, request, response handling, records (sync path)

**Files:**
- Create: `SourceScout/sourcescout/extract.py`, `SourceScout/tests/test_extract.py`

**Interfaces:**
- Consumes: `ExtractionCfg`, `Registry`, `Source`, `Category`, `Store`, `StoredItem`, `RunReport`, schema module, `ExtractionConfigError`, `utcnow`, `iso`.
- Produces:
  - `SYSTEM_PROMPT: str`; `render_item(item, source, category) -> str`; `build_params(cfg, item, source, category) -> dict` (usable for both `client.messages.create(**params)` and a batch request's `params`).
  - `quote_in_text(quote, text) -> bool`.
  - `ExtractContext(cfg, registry, store, report, output_dir, run_id)` dataclass.
  - `handle_message(ctx, item, message) -> None` (one path for sync and batch results).
  - `run_extraction(ctx, client, *, batch: bool, limit: int | None = None, sleep=time.sleep) -> None` (signature final; the batch branch is completed in Task 8).
  - `make_client() -> anthropic.Anthropic` (raises `ExtractionConfigError` when no credential is resolvable).
  - `recent_references(output_dir, since: datetime) -> list[tuple[str, str]]` (url, item_id) — used by discovery.

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_extract.py`:
```python
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
import yaml

from conftest import make_registry
from sourcescout.adapters.base import RawItem
from sourcescout.config import load_config
from sourcescout.errors import ExtractionConfigError
from sourcescout.extract import (ExtractContext, build_params, make_client, quote_in_text, recent_references,
                                 run_extraction)
from sourcescout.report import RunReport
from sourcescout.store import Store, item_id_for

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
TEXT = "The agency seeks methods for “long-horizon planning”, which remains an open challenge.\nAwards up to $1.5M."


def message(payload, output_tokens=800, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=1200, output_tokens=output_tokens, cache_read_input_tokens=0))


def cand(unsolved='for "long-horizon planning", which remains an open challenge', pay="Awards up to $1.5M."):
    return {"statement": "Long-horizon planning methods.", "why_interesting": "Agency funds it.",
            "explicit_unsolved_signal": {"present": True, "evidence": unsolved},
            "payment_signal": {"type": "grant", "stated": "$1.5M", "evidence": pay, "deadline": "2026-12-01"},
            "technical_area": ["planning"], "entities": {"organizations": ["NSF"], "researchers": []},
            "referenced_urls": ["https://org.example/call"]}


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **params):
        self.calls.append(params)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def ctx(paths):
    reg = make_registry(paths, [{"id": "g", "name": "G", "category": "gov_solicitation", "kind": "page",
                                 "url": "https://g.example"}])
    store = Store(paths.db)
    return ExtractContext(load_config(paths.config).extraction, reg, store, RunReport.new(NOW), paths.output, "RUN1")


def add_item(ctx, url="https://g.example/1"):
    ctx.store.upsert(RawItem("g", url, "Call 1", "2026-09-01", TEXT, ("https://org.example/call",)), "2026-09-30T00:00:00+00:00", 20000)


def test_build_params(ctx):
    add_item(ctx)
    [item] = ctx.store.pending()
    p = build_params(ctx.cfg, item, ctx.registry.get("g"), ctx.registry.categories["gov_solicitation"])
    assert p["model"] == "claude-opus-5-5" and p["max_tokens"] == 4000
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert p["output_config"]["effort"] == "low" and p["output_config"]["format"]["type"] == "json_schema"
    user = p["messages"][0]["content"]
    assert "long-horizon planning" in user and "https://org.example/call" in user and 'tier="A"' in user


def test_quote_in_text_normalises_quotes_and_whitespace():
    assert quote_in_text('for "long-horizon  planning", which', TEXT)
    assert not quote_in_text("the agency wants better planning", TEXT)
    assert not quote_in_text("", TEXT)
    assert quote_in_text("better forecasting.", "We need better\nforecasting\n.")


def test_sync_writes_records(ctx):
    add_item(ctx)
    client = FakeClient([message({"candidates": [cand(), cand(pay="paraphrased funding")]})])
    run_extraction(ctx, client, batch=False)
    files = sorted(ctx.output_dir.glob("*/*.yaml"))
    assert len(files) == 2
    recs = [yaml.safe_load(f.read_text()) for f in files]
    assert [r["evidence_verified"] for r in recs] == [True, False]
    r0 = recs[0]
    assert r0["source"] == {"url": "https://g.example/1", "title": "Call 1", "date": "2026-09-01",
                            "tier": "A", "category": "gov_solicitation"}
    assert r0["candidate_id"].endswith("-r1-0") and r0["extracted_with"]["output_tokens"] == 400
    st = ctx.report.extract["g"]
    assert (st.items, st.candidates, st.output_tokens, st.unverified) == (1, 2, 800, 1)
    assert ctx.store.pending() == [] and ctx.registry.get("g").yield_.candidates == 2
    assert ctx.registry.get("g").yield_.scans_since_candidate == 0


def test_zero_candidates_marks_done(ctx):
    add_item(ctx)
    run_extraction(ctx, FakeClient([message({"candidates": []}, output_tokens=50)]), batch=False)
    assert list(ctx.output_dir.glob("*/*.yaml")) == [] and ctx.store.pending() == []


@pytest.mark.parametrize("outcome, needle", [
    (message({"candidates": []}, stop_reason="max_tokens"), "max_tokens"),
    (message("not json"), "schema"),
    (message({"candidates": [cand()] * 4}), "schema"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "api"),
])
def test_item_failures_are_recorded_and_run_continues(ctx, outcome, needle):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    run_extraction(ctx, FakeClient([outcome, message({"candidates": [cand()]})]), batch=False)
    assert len(ctx.report.failures) == 1 and needle in ctx.report.failures[0]["error"]
    assert ctx.report.extract["g"].candidates == 1


def test_auth_error_is_config_error(ctx):
    add_item(ctx)
    err = anthropic.AuthenticationError("bad key", response=httpx2.Response(
        401, request=httpx2.Request("POST", "https://api.anthropic.com")), body=None)
    with pytest.raises(ExtractionConfigError):
        run_extraction(ctx, FakeClient([err]), batch=False)


def test_make_client_without_credentials(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ExtractionConfigError):
        make_client()


def test_recent_references(ctx):
    add_item(ctx)
    run_extraction(ctx, FakeClient([message({"candidates": [cand()]})]), batch=False)
    assert recent_references(ctx.output_dir, NOW - timedelta(days=1)) == [
        ("https://org.example/call", item_id_for("https://g.example/1"))]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_extract.py -v`
Expected: FAIL (`ModuleNotFoundError: sourcescout.extract`).

- [ ] **Step 3: Implement `SourceScout/sourcescout/extract.py`** (sync branch + shared handling; Task 8 fills `_run_batch`)

```python
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import anthropic
import yaml
from pydantic import ValidationError

from sourcescout.categories import Category
from sourcescout.config import ExtractionCfg
from sourcescout.errors import ExtractionConfigError
from sourcescout.registry import Registry, Source
from sourcescout.report import RunReport
from sourcescout.schema import EXTRACTION_SCHEMA, ExtractionResult, length_violations
from sourcescout.store import Store, StoredItem
from sourcescout.timeutil import iso, utcnow

SYSTEM_PROMPT = """You extract candidate technical problems from one source document for a problem-discovery pipeline.

A candidate is a concrete technical problem (engineering, machine learning, data science, optimisation, computational biology, or similar) that the document states is unsolved, not solved well enough, or that the publishing organisation is seeking or funding a solution for.

Extract; do not analyse. Report only what the document states. Do not estimate value, feasibility, market size or difficulty, and do not add knowledge from outside the document.

Rules:
- Return at most 3 candidates. Return an empty list when the document states no such problem, for example a sales, legal or generic operations job ad, a product announcement, or a write-up of a solved problem.
- statement: the problem in at most 60 words, in plain technical language.
- why_interesting: one sentence of at most 30 words restating what the document says makes it matter (who needs it, stated scale or cost). No speculation.
- explicit_unsolved_signal: present is true only if the document itself says the problem is open, unsolved, a limitation, a challenge, or being sought. evidence is a verbatim quote of at most 50 words; an empty string when present is false.
- payment_signal: type is one of prize, grant, contract, hiring, investor_thesis, none_stated. A job posting for a role whose work is to solve the problem is hiring. stated is the amount, headcount or funding as written (empty string if none). evidence is a verbatim quote of at most 50 words supporting it; an empty string when type is none_stated. deadline is the stated submission or closing date as YYYY-MM-DD, or null.
- Quotes are copied character for character from the document text: no ellipses, no paraphrase, no merged fragments.
- technical_area: at most 3 short tags, e.g. "reinforcement learning", "protein design".
- entities: organisations and named researchers mentioned in connection with the problem.
- referenced_urls: at most 5 URLs from the document's link list that point to the official call, challenge, dataset, or the organisation's own pages about the problem."""


def render_item(item: StoredItem, source: Source, category: Category) -> str:
    links = "\n".join(item.links[:50])
    return (f'<document source_id="{source.id}" category="{category.id}" tier="{category.tier}">\n'
            f"<title>{item.title}</title>\n<url>{item.url}</url>\n<published>{item.published or ''}</published>\n"
            f"<text>\n{item.text}\n</text>\n<links>\n{links}\n</links>\n</document>")


def build_params(cfg: ExtractionCfg, item: StoredItem, source: Source, category: Category) -> dict:
    return {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "output_config": {"effort": cfg.effort, "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        "messages": [{"role": "user", "content": render_item(item, source, category)}],
    }


_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).translate(_QUOTES))
    return re.sub(r" ([.,;:!?)\]])", r"\1", s).strip()  # html_to_text puts inline tags on own lines


def quote_in_text(quote: str, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(text)


@dataclass
class ExtractContext:
    cfg: ExtractionCfg
    registry: Registry
    store: Store
    report: RunReport
    output_dir: Path
    run_id: str


def make_client() -> anthropic.Anthropic:
    client = anthropic.Anthropic()
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        raise ExtractionConfigError("No Anthropic credentials found",
                                    fix="export ANTHROPIC_API_KEY=... (or run `ant auth login`)")
    return client


def _fail(ctx: ExtractContext, item: StoredItem, error: str) -> None:
    ctx.store.mark_failed(item.item_id, error)
    ctx.report.extract_stat(item.source_id).failed += 1
    ctx.report.failures.append({"source_id": item.source_id, "item_id": item.item_id, "error": error})


def _raise_if_not_transient(e: anthropic.APIError) -> None:
    """Errors a retry cannot fix (auth, permission, bad model, bad request) abort the run."""
    if isinstance(e, (anthropic.APIConnectionError, anthropic.RateLimitError)):
        return
    if isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
        return
    raise ExtractionConfigError(f"Anthropic API rejected the request: {e}",
                                fix="Check credentials, the model name in config.yaml, and the request schema") from e


def _required_quotes(c) -> tuple[list[str], bool]:
    """Quotes that must be found in the source, and whether none of them is empty."""
    required = []
    if c.explicit_unsolved_signal.present:
        required.append(c.explicit_unsolved_signal.evidence)
    if c.payment_signal.type != "none_stated":
        required.append(c.payment_signal.evidence)
    return required, all(bool(q) for q in required)


def handle_message(ctx: ExtractContext, item: StoredItem, message) -> None:
    stat = ctx.report.extract_stat(item.source_id)
    stat.items += 1
    usage = message.usage
    stat.output_tokens += usage.output_tokens
    stat.input_tokens += usage.input_tokens
    stat.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
    if message.stop_reason in ("refusal", "max_tokens"):
        return _fail(ctx, item, f"stop_reason={message.stop_reason}")
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        return _fail(ctx, item, "no text block in response")
    try:
        result = ExtractionResult.model_validate_json(text)
    except ValidationError as e:
        return _fail(ctx, item, f"schema: {e.errors()[:3]}")
    source = ctx.registry.find(item.source_id)
    if source is None:
        return _fail(ctx, item, f"source {item.source_id!r} no longer in registry")
    category = ctx.registry.categories[source.category]
    now = utcnow()
    share = round(usage.output_tokens / len(result.candidates)) if result.candidates else 0
    for idx, c in enumerate(result.candidates):
        quotes, present = _required_quotes(c)
        verified = present and all(quote_in_text(q, item.text) for q in quotes)
        violations = length_violations(c)
        stat.unverified += int(not verified)
        stat.length_violations += int(bool(violations))
        record = {
            "source_id": source.id, "item_id": item.item_id,
            "candidate_id": f"cand-{item.item_id}-r{item.revision}-{idx}", "revision": item.revision,
            "source": {"url": item.url, "title": item.title, "date": item.published,
                       "tier": category.tier, "category": category.id},
            "candidate_problem": {"statement": c.statement},
            "why_interesting": c.why_interesting,
            "explicit_unsolved_signal": c.explicit_unsolved_signal.model_dump(),
            "payment_signal": c.payment_signal.model_dump(),
            "technical_area": c.technical_area,
            "entities": c.entities.model_dump(),
            "referenced_urls": c.referenced_urls,
            "evidence_verified": verified,
            "length_violations": violations,
            "extracted_with": {"model": ctx.cfg.model, "run_id": ctx.run_id, "output_tokens": share, "at": iso(now)},
        }
        out_dir = ctx.output_dir / now.strftime("%Y-%m")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{record['candidate_id']}.yaml").write_text(
            yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8")
    stat.candidates += len(result.candidates)
    if result.candidates:
        source.yield_.candidates += len(result.candidates)
        source.yield_.scans_since_candidate = 0
    ctx.store.mark_done(item.item_id)


def _params_for(ctx: ExtractContext, item: StoredItem) -> dict | None:
    source = ctx.registry.find(item.source_id)
    if source is None:
        _fail(ctx, item, f"source {item.source_id!r} no longer in registry")
        return None
    return build_params(ctx.cfg, item, source, ctx.registry.categories[source.category])


def _run_sync(ctx: ExtractContext, client, limit: int | None) -> None:
    for item in ctx.store.pending(limit):
        params = _params_for(ctx, item)
        if params is None:
            continue
        try:
            message = client.messages.create(**params)
        except anthropic.APIError as e:
            _raise_if_not_transient(e)
            _fail(ctx, item, f"api: {e}")
            continue
        handle_message(ctx, item, message)


def run_extraction(ctx: ExtractContext, client, *, batch: bool, limit: int | None = None, sleep=time.sleep) -> None:
    try:
        if batch:
            _run_batch(ctx, client, limit, sleep)
        else:
            _run_sync(ctx, client, limit)
    finally:
        ctx.registry.save()


def recent_references(output_dir: Path, since: datetime) -> list[tuple[str, str]]:
    out = []
    month = since.strftime("%Y-%m")
    for path in sorted(output_dir.glob("*/*.yaml")):
        if path.parent.name < month:
            continue
        rec = yaml.safe_load(path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(rec["extracted_with"]["at"]) >= since:
            out += [(url, rec["item_id"]) for url in rec.get("referenced_urls") or []]
    return out
```

Add this temporary `_run_batch` to `extract.py`; Task 8 (the next task) replaces it:

```python
def _run_batch(ctx: ExtractContext, client, limit: int | None, sleep) -> None:
    raise ExtractionConfigError("batch extraction is implemented in Task 8", fix="Use --sync until Task 8 lands")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SourceScout/sourcescout/extract.py SourceScout/tests/test_extract.py && git commit -m "feat: shallow candidate extraction via Claude structured output (sync path)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Extractor — Message Batches path with resume

**Files:**
- Modify: `SourceScout/sourcescout/extract.py` (replace `_run_batch` stub)
- Create: `SourceScout/tests/test_extract_batch.py`

**Interfaces:**
- Consumes: Task 7 internals (`_params_for`, `handle_message`, `_fail`, `_raise_if_not_transient`), `Store.mark_submitted/submitted_batch_ids/items_in_batch/reset_pending`.
- Produces: `_run_batch(ctx, client, limit, sleep)`; `_collect_batch(ctx, client, batch_id, sleep)`.

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_extract_batch.py`:
```python
from types import SimpleNamespace

from test_extract import add_item, cand, ctx, message  # noqa: F401  (fixture re-export)
from sourcescout.extract import run_extraction
from sourcescout.store import item_id_for


class FakeBatches:
    def __init__(self, results_by_batch=None):
        self.created = []
        self.results_by_batch = results_by_batch or {}
        self.polls = 0

    def create(self, requests):
        bid = f"b{len(self.created) + 1}"
        self.created.append(requests)
        self.results_by_batch.setdefault(bid, [
            SimpleNamespace(custom_id=r["custom_id"],
                            result=SimpleNamespace(type="succeeded", message=message({"candidates": [cand()]})))
            for r in requests])
        return SimpleNamespace(id=bid, processing_status="in_progress")

    def retrieve(self, batch_id):
        self.polls += 1
        return SimpleNamespace(id=batch_id, processing_status="ended" if self.polls > 1 else "in_progress")

    def results(self, batch_id):
        return iter(self.results_by_batch[batch_id])


def client_with(batches):
    return SimpleNamespace(messages=SimpleNamespace(batches=batches))


def test_batch_submit_and_collect(ctx):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    batches = FakeBatches()
    sleeps = []
    run_extraction(ctx, client_with(batches), batch=True, sleep=sleeps.append)
    [requests] = batches.created
    assert {r["custom_id"] for r in requests} == {item_id_for("https://g.example/1"), item_id_for("https://g.example/2")}
    assert requests[0]["params"]["output_config"]["format"]["type"] == "json_schema"
    assert sleeps == [ctx.cfg.batch_poll_seconds]
    assert ctx.report.extract["g"].candidates == 2 and ctx.store.pending() == []


def test_resume_collects_previously_submitted_batch(ctx):
    add_item(ctx, "https://g.example/1")
    [item] = ctx.store.pending()
    ctx.store.mark_submitted([item.item_id], "old")
    old = [SimpleNamespace(custom_id=item.item_id,
                           result=SimpleNamespace(type="succeeded", message=message({"candidates": [cand()]})))]
    batches = FakeBatches({"old": old})
    run_extraction(ctx, client_with(batches), batch=True, sleep=lambda s: None)
    assert batches.created == []  # nothing resubmitted
    assert ctx.report.extract["g"].candidates == 1 and ctx.store.submitted_batch_ids() == []


def test_expired_goes_back_to_pending_and_errored_fails(ctx):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    a, b = [i.item_id for i in ctx.store.pending()]
    ctx.store.mark_submitted([a, b], "old")
    results = [SimpleNamespace(custom_id=a, result=SimpleNamespace(type="expired")),
               SimpleNamespace(custom_id=b, result=SimpleNamespace(type="errored", error="invalid_request"))]
    batches = FakeBatches({"old": results})
    # expired item is resubmitted in the same run and succeeds there
    run_extraction(ctx, client_with(batches), batch=True, sleep=lambda s: None)
    assert len(batches.created) == 1 and [r["custom_id"] for r in batches.created[0]] == [a]
    assert ctx.store.get(b).extract_status == "failed"
    assert ctx.store.get(a).extract_status == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_extract_batch.py -v`
Expected: FAIL (`ExtractionConfigError: batch extraction is implemented in Task 8`).

- [ ] **Step 3: Implement** — replace the `_run_batch` stub in `extract.py`, and add the two imports at the top of the file:

```python
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
```

```python
def _collect_batch(ctx: ExtractContext, client, batch_id: str, sleep) -> None:
    try:
        while client.messages.batches.retrieve(batch_id).processing_status != "ended":
            sleep(ctx.cfg.batch_poll_seconds)
        results = list(client.messages.batches.results(batch_id))
    except anthropic.APIError as e:
        _raise_if_not_transient(e)
        ctx.report.failures.append({"source_id": "*", "item_id": "*",
                                    "error": f"batch {batch_id} not collected (kept for next run): {e}"})
        return
    items = ctx.store.items_in_batch(batch_id)
    for r in results:
        item = items.pop(r.custom_id, None)
        if item is None:
            continue
        kind = r.result.type
        if kind == "succeeded":
            handle_message(ctx, item, r.result.message)
        elif kind == "errored":
            _fail(ctx, item, f"batch errored: {r.result.error}")
        else:  # canceled / expired: external, retry next submission
            ctx.store.reset_pending(item.item_id)
    for item in items.values():  # no result returned for these
        ctx.store.reset_pending(item.item_id)


def _run_batch(ctx: ExtractContext, client, limit: int | None, sleep) -> None:
    for batch_id in ctx.store.submitted_batch_ids():
        _collect_batch(ctx, client, batch_id, sleep)
    requests = []
    for item in ctx.store.pending(limit):
        params = _params_for(ctx, item)
        if params is not None:
            requests.append(Request(custom_id=item.item_id, params=MessageCreateParamsNonStreaming(**params)))
    if not requests:
        return
    try:
        batch = client.messages.batches.create(requests=requests)
    except anthropic.APIError as e:
        _raise_if_not_transient(e)
        ctx.report.failures.append({"source_id": "*", "item_id": "*", "error": f"batch submit failed (items stay pending): {e}"})
        return
    ctx.store.mark_submitted([r["custom_id"] for r in requests], batch.id)
    _collect_batch(ctx, client, batch.id, sleep)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SourceScout/sourcescout/extract.py SourceScout/tests/test_extract_batch.py && git commit -m "feat: batch extraction with resume of submitted batches

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Discovery of new sources

**Files:**
- Create: `SourceScout/sourcescout/discover.py`, `SourceScout/tests/test_discover.py`

**Interfaces:**
- Consumes: `Registry`, `Source`, `Fetcher`, `DiscoveryCfg`, `RunReport`, `SourceFetchError`, `selectolax`.
- Produces: `job_board_source(url, origin, title_include) -> Source | None`; `find_feed(html, base_url) -> str | None`; `blog_like(url) -> bool`; `discover(registry, http, cfg, refs, links, report, unmapped_path) -> None` — `refs`: candidate `referenced_urls` (feed autodiscovery + job patterns); `links`: outbound links of newly seen items (job patterns only, no fetching). Saves the registry.

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_discover.py`:
```python
from datetime import datetime, timezone

import yaml

from conftest import make_fetcher, make_registry
from sourcescout.config import load_config
from sourcescout.discover import blog_like, discover, find_feed, job_board_source
from sourcescout.report import RunReport

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def test_job_board_patterns():
    s = job_board_source("https://job-boards.greenhouse.io/acme/jobs/123", "item1", "(?i)research")
    assert (s.id, s.kind, s.url, s.status, s.provenance, s.category) == (
        "greenhouse-acme", "greenhouse", "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
        "candidate", "discovered_from:item1", "job_board")
    assert s.params == {"title_include": "(?i)research"}
    assert job_board_source("https://jobs.lever.co/acme/abc", "i", "x").url == "https://api.lever.co/v0/postings/acme?mode=json"
    assert job_board_source("https://jobs.ashbyhq.com/acme", "i", "x").url == "https://api.ashbyhq.com/posting-api/job-board/acme"
    assert job_board_source("https://example.com/jobs", "i", "x") is None


def test_find_feed_and_blog_like():
    html = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>'
    assert find_feed(html, "https://eng.acme.example/post") == "https://eng.acme.example/feed.xml"
    assert find_feed("<html></html>", "https://x.example") is None
    assert blog_like("https://engineering.acme.example/x") and blog_like("https://acme.example/blog/x")
    assert not blog_like("https://acme.example/products")


def test_discover_adds_candidates_and_writes_unmapped(paths):
    reg = make_registry(paths, [{"id": "rss-known", "name": "k", "category": "tech_blog", "kind": "rss",
                                 "url": "https://known.example/feed"}])
    feed_page = '<html><head><link rel="alternate" type="application/atom+xml" href="https://blog.new.example/atom"></head></html>'
    routes = {"GET https://blog.new.example/post/1": feed_page,
              "GET https://corp.example/about": "<html><body>no feed</body></html>"}
    cfg = load_config(paths.config).discovery
    report = RunReport.new(NOW)
    refs = [("https://blog.new.example/post/1", "i1"), ("https://corp.example/about", "i2"),
            ("https://known.example/other", "i3"), ("https://twitter.com/acme", "i4")]
    links = [("https://jobs.lever.co/acme/1", "i5"), ("https://jobs.lever.co/acme/2", "i6")]
    discover(reg, make_fetcher(routes), cfg, refs, links, report, paths.unmapped)
    ids = {s.id for s in reg.sources}
    assert {"rss-blog-new-example", "lever-acme"} <= ids and len(ids) == 3
    assert reg.get("rss-blog-new-example").url == "https://blog.new.example/atom"
    assert set(report.discovered) == {"rss-blog-new-example", "lever-acme"}
    unmapped = yaml.safe_load(paths.unmapped.read_text())
    assert [u["url"] for u in unmapped] == ["https://corp.example/about"]
    # second run: nothing new, unmapped not duplicated
    discover(reg, make_fetcher(routes), cfg, refs, links, RunReport.new(NOW), paths.unmapped)
    assert len(reg.sources) == 3 and len(yaml.safe_load(paths.unmapped.read_text())) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_discover.py -v`
Expected: FAIL (`ModuleNotFoundError: sourcescout.discover`).

- [ ] **Step 3: Implement `SourceScout/sourcescout/discover.py`**

```python
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml
from selectolax.parser import HTMLParser

from sourcescout.config import DiscoveryCfg
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher
from sourcescout.registry import Registry, Source
from sourcescout.report import RunReport

_JOB_PATTERNS = [
    (re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/([A-Za-z0-9_-]+)"), "greenhouse",
     "https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true"),
    (re.compile(r"^https?://jobs\.lever\.co/([A-Za-z0-9_-]+)"), "lever",
     "https://api.lever.co/v0/postings/{t}?mode=json"),
    (re.compile(r"^https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"), "ashby",
     "https://api.ashbyhq.com/posting-api/job-board/{t}"),
]
_FEED_TYPES = ("application/rss+xml", "application/atom+xml")


def job_board_source(url: str, origin: str, title_include: str) -> Source | None:
    for pattern, kind, api in _JOB_PATTERNS:
        m = pattern.match(url)
        if m:
            token = m.group(1)
            return Source(id=f"{kind}-{token.lower()}", name=f"{token} ({kind})", category="job_board", kind=kind,
                          url=api.format(t=token), params={"title_include": title_include},
                          status="candidate", provenance=f"discovered_from:{origin}")
    return None


def find_feed(html: str, base_url: str) -> str | None:
    for link in HTMLParser(html).css('link[rel="alternate"]'):
        if (link.attributes.get("type") or "").lower() in _FEED_TYPES and link.attributes.get("href"):
            return urljoin(base_url, link.attributes["href"])
    return None


def blog_like(url: str) -> bool:
    p = urlsplit(url)
    return p.netloc.lower().startswith(("engineering.", "blog.", "tech.", "research.")) or \
        bool(re.search(r"/(blog|engineering)(/|$)", p.path))


def _ignored(host: str, cfg: DiscoveryCfg) -> bool:
    return any(host == h or host.endswith("." + h) for h in cfg.ignore_hosts)


def discover(registry: Registry, http: Fetcher, cfg: DiscoveryCfg, refs: list[tuple[str, str]],
             links: list[tuple[str, str]], report: RunReport, unmapped_path: Path) -> None:
    for url, origin in refs + links:
        s = job_board_source(url, origin, cfg.job_title_include)
        if s and registry.find(s.id) is None:
            registry.add(s)
            report.discovered.append(s.id)

    unmapped = (yaml.safe_load(unmapped_path.read_text(encoding="utf-8")) or []) if unmapped_path.exists() else []
    known_unmapped = {u["url"] for u in unmapped}
    known_hosts = {urlsplit(s.url).netloc.lower() for s in registry.sources}
    fetches = 0
    for url, origin in refs:
        host = urlsplit(url).netloc.lower()
        if not host or _ignored(host, cfg) or host in known_hosts or job_board_source(url, origin, "") or url in known_unmapped:
            continue
        if fetches >= cfg.max_fetches_per_run:
            report.discovery_errors.append(f"fetch cap {cfg.max_fetches_per_run} reached; remaining references skipped")
            break
        fetches += 1
        known_hosts.add(host)
        try:
            resp = http.get(url)
        except SourceFetchError as e:
            report.discovery_errors.append(str(e))
            continue
        feed = find_feed(resp.text, str(resp.url))
        if feed and blog_like(url):
            sid = "rss-" + re.sub(r"[^a-z0-9]+", "-", host).strip("-")
            if registry.find(sid) is None:
                registry.add(Source(id=sid, name=host, category="tech_blog", kind="rss", url=feed,
                                    status="candidate", provenance=f"discovered_from:{origin}"))
                report.discovered.append(sid)
        else:
            unmapped.append({"url": url, "feed": feed, "discovered_from": origin})
            known_unmapped.add(url)
            report.unmapped.append(url)
    unmapped_path.write_text(yaml.safe_dump(unmapped, sort_keys=False), encoding="utf-8")
    registry.save()
```

Note: `known_hosts` is computed from registry source URLs, so `https://known.example/other` is skipped because `rss-known` has host `known.example`. For API-based sources (e.g. `boards-api.greenhouse.io`) this host set is irrelevant to feed discovery.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SourceScout/sourcescout/discover.py SourceScout/tests/test_discover.py && git commit -m "feat: deterministic discovery of job boards and blog feeds

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: CLI and README

**Files:**
- Create: `SourceScout/sourcescout/cli.py`, `SourceScout/README.md`, `SourceScout/tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `cli.app` (typer) with commands `scan`, `extract`, `discover`, `run`, `report`, and `sources list|check|promote|retire`; global `--root PATH` (default `DEFAULT_ROOT`).

- [ ] **Step 1: Write the failing tests**

`SourceScout/tests/test_cli.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest SourceScout/tests/test_cli.py -v`
Expected: FAIL (`ModuleNotFoundError: sourcescout.cli`).

- [ ] **Step 3: Implement `SourceScout/sourcescout/cli.py`**

```python
import functools
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import typer

from sourcescout.adapters import KINDS, REQUIRED_PARAMS
from sourcescout.categories import load_categories
from sourcescout.config import DEFAULT_ROOT, Config, Paths, load_config
from sourcescout.discover import discover as run_discover
from sourcescout.errors import ScoutError, SourceFetchError
from sourcescout.extract import ExtractContext, make_client, recent_references, run_extraction
from sourcescout.http import Fetcher
from sourcescout.lifecycle import apply_lifecycle
from sourcescout.registry import Health, Registry
from sourcescout.report import RunReport
from sourcescout.scan import scan as run_scan
from sourcescout.store import Store
from sourcescout.timeutil import iso, utcnow

app = typer.Typer(no_args_is_help=True, help="SourceScout: collect newly exposed, paid-for technical problems.")
sources_app = typer.Typer(no_args_is_help=True, help="Inspect and manage registry sources.")
app.add_typer(sources_app, name="sources")


@dataclass
class Env:
    paths: Paths
    config: Config
    registry: Registry
    store: Store
    http: Fetcher


def _env(root: Path) -> Env:
    paths = Paths(root)
    config = load_config(paths.config)
    registry = Registry.load(paths.registry, load_categories(paths.categories), REQUIRED_PARAMS)
    return Env(paths, config, registry, Store(paths.db), Fetcher(config.http))


def clean_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ScoutError as e:
            typer.echo(f"ERROR: {e}", err=True)
            if e.fix:
                typer.echo(f"Fix: {e.fix}", err=True)
            raise typer.Exit(1)
    return wrapper


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="SourceScout directory")):
    ctx.obj = root


def _finish(env: Env, report: RunReport) -> None:
    report.lifecycle += apply_lifecycle(env.registry, env.config.lifecycle)
    env.registry.save()
    path = report.save(env.paths.runs)
    typer.echo(report.render(env.config.extraction.token_budget_per_candidate))
    typer.echo(f"\nReport saved: {path}")


def _scan(env: Env, report: RunReport, now: datetime, **filters) -> None:
    run_scan(env.registry, env.store, env.http, report, now=now,
             max_item_chars=env.config.extraction.max_item_chars, **filters)


def _extract(env: Env, report: RunReport, batch: bool, limit: int | None) -> None:
    ctx = ExtractContext(env.config.extraction, env.registry, env.store, report, env.paths.output, report.run_id)
    run_extraction(ctx, make_client(), batch=batch, limit=limit)


def _discover(env: Env, report: RunReport, since: datetime) -> None:
    run_discover(env.registry, env.http, env.config.discovery, recent_references(env.paths.output, since),
                 env.store.links_first_seen_since(iso(since)), report, env.paths.unmapped)


@app.command()
@clean_errors
def scan(ctx: typer.Context, source: str = typer.Option(None, help="Scan only this source id"),
         category: str = typer.Option(None), tier: str = typer.Option(None),
         force: bool = typer.Option(False, help="Ignore cadence")):
    """Fetch due sources and store new/changed items."""
    env, now = _env(ctx.obj), utcnow()
    report = RunReport.new(now)
    _scan(env, report, now, source_id=source, category=category, tier=tier, force=force)
    _finish(env, report)


@app.command()
@clean_errors
def extract(ctx: typer.Context, batch: bool = typer.Option(True, "--batch/--sync"),
            limit: int = typer.Option(None, help="Max items to extract")):
    """Extract candidates from pending items (Batches API by default)."""
    env = _env(ctx.obj)
    report = RunReport.new(utcnow())
    _extract(env, report, batch, limit)
    _finish(env, report)


@app.command()
@clean_errors
def discover(ctx: typer.Context, days: float = typer.Option(1.0, help="Look back this many days")):
    """Propose new sources from recent items and candidates."""
    env, now = _env(ctx.obj), utcnow()
    report = RunReport.new(now)
    _discover(env, report, now - timedelta(days=days))
    _finish(env, report)


@app.command()
@clean_errors
def run(ctx: typer.Context, batch: bool = typer.Option(True, "--batch/--sync"),
        limit: int = typer.Option(None, help="Max items to extract")):
    """scan -> extract -> discover -> lifecycle -> report."""
    env, now = _env(ctx.obj), utcnow()
    report = RunReport.new(now)
    _scan(env, report, now)
    _extract(env, report, batch, limit)
    _discover(env, report, now)
    _finish(env, report)


@app.command()
@clean_errors
def report(ctx: typer.Context, run_id: str = typer.Option(None, "--run-id")):
    """Print a saved run report (latest by default)."""
    paths = Paths(ctx.obj)
    path = paths.runs / f"{run_id}.json" if run_id else RunReport.latest(paths.runs)
    if path is None or not path.exists():
        raise ScoutError("No run reports found", fix="Run `uv run sourcescout run` first")
    budget = load_config(paths.config).extraction.token_budget_per_candidate
    typer.echo(RunReport.load(path).render(budget))


@sources_app.command("list")
@clean_errors
def sources_list(ctx: typer.Context):
    env = _env(ctx.obj)
    for s in env.registry.sources:
        y = s.yield_
        typer.echo(f"{s.id:32} {s.status:9} {s.category:20} {s.kind:10} scans={y.scans} cand={y.candidates} "
                   f"fail={s.health.consecutive_failures}")


@sources_app.command("check")
@clean_errors
def sources_check(ctx: typer.Context, source_id: str):
    """Fetch one source without storing anything; prints what an extraction would see."""
    env = _env(ctx.obj)
    s = env.registry.get(source_id)
    try:
        items = KINDS[s.kind].fetch(s, env.http, lambda url: False)
    except SourceFetchError as e:
        raise ScoutError(f"{source_id}: {e}", fix="Correct the url/params in registry.yaml or drop the source")
    typer.echo(f"{source_id}: {len(items)} items")
    for it in items[:3]:
        typer.echo(f"  - {it.title[:80]} | {it.url} | {len(it.text)} chars, {len(it.links)} links")


def _set_status(root: Path, source_id: str, status: str) -> None:
    env = _env(root)
    s = env.registry.get(source_id)
    s.status = status
    if status == "active":
        s.health = Health(last_ok=s.health.last_ok)
        s.yield_.scans_since_candidate = 0
    env.registry.save()
    typer.echo(f"{source_id}: {status}")


@sources_app.command("promote")
@clean_errors
def sources_promote(ctx: typer.Context, source_id: str):
    _set_status(ctx.obj, source_id, "active")


@sources_app.command("retire")
@clean_errors
def sources_retire(ctx: typer.Context, source_id: str):
    _set_status(ctx.obj, source_id, "retired")
```

- [ ] **Step 4: Write `SourceScout/README.md`**

````markdown
# SourceScout

Collects *newly exposed technical problems that somebody has a reason to pay to solve* from funded calls,
challenge platforms, job boards, investor theses, engineering blogs and workshop calls. It extracts shallow
candidate records only — no value estimation or triage (later stages).

## Files
- `sources.yaml` — category classes (tier, enabled). Enable a category to scan its sources.
- `registry.yaml` — concrete sources (rewritten by the tool; comments are not preserved).
- `config.yaml` — model, effort, token budget, lifecycle and HTTP settings.
- `output/YYYY-MM/*.yaml` — one candidate per file (format: `scout_output_schema.yaml`).
- `data/` — SQLite item store and run reports (not versioned).
- `discovered_unmapped.yaml` — discovered URLs that fit no category; review by hand.

## Usage
```bash
export ANTHROPIC_API_KEY=...            # or `ant auth login`
uv run sourcescout run                  # scan -> extract (batch) -> discover -> report
uv run sourcescout run --sync --limit 5 # small synchronous run
uv run sourcescout scan --tier A --force
uv run sourcescout sources list
uv run sourcescout sources check <id>   # dry fetch of one source
uv run sourcescout report               # latest run report
```

## Source kinds
`rss` (params: `max_items`, `fetch_full`), `greenhouse`, `lever`, `ashby`, `grants_gov` (`keyword`, `rows`,
`opp_statuses`), `html_list` (`link_selector`, `link_pattern`, `max_items`, `content_selector`),
`page` (`content_selector`). Every kind accepts `title_include` / `title_exclude` regexes.

## Lifecycle
Discovered sources start as `candidate`; promoted on their first candidate, retired after
`promote_within_scans` scans without one. Active sources are retired after `retire_zero_yield_active`
scans without a candidate or `max_consecutive_failures` failed fetches. `sources promote|retire` overrides.
````

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest SourceScout/tests -v && uv run sourcescout --help`
Expected: all PASS; help lists `scan extract discover run report sources`.

- [ ] **Step 6: Commit**

```bash
git add SourceScout/sourcescout/cli.py SourceScout/README.md SourceScout/tests/test_cli.py && git commit -m "feat: sourcescout CLI with clean operator errors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Seed registry and live verification

**Files:**
- Create: `SourceScout/registry.yaml` (replace `sources: []`), `SourceScout/tests/test_live.py`

**Interfaces:**
- Consumes: CLI `sources check`, `run`.

- [ ] **Step 1: Add seed entries** to `SourceScout/registry.yaml`, one at a time, each verified with `uv run sourcescout sources check <id>` (must print ≥ 1 item with non-trivial text). Keep an entry only if the check passes; otherwise remove it and record `<id>: <reason>` for the final report. Seeds:

Tier A (`gov_solicitation` / `challenge_platform`):
```yaml
- {id: grants-gov-ml, name: "grants.gov: machine learning", category: gov_solicitation, kind: grants_gov,
   url: "https://api.grants.gov/v1/api/search2", params: {keyword: "machine learning", rows: 50}}
- {id: grants-gov-ai, name: "grants.gov: artificial intelligence", category: gov_solicitation, kind: grants_gov,
   url: "https://api.grants.gov/v1/api/search2", params: {keyword: "artificial intelligence", rows: 50}}
- {id: grants-gov-protein, name: "grants.gov: protein engineering", category: gov_solicitation, kind: grants_gov,
   url: "https://api.grants.gov/v1/api/search2", params: {keyword: "protein engineering", rows: 50}}
- {id: grants-gov-decision, name: "grants.gov: autonomous decision making", category: gov_solicitation, kind: grants_gov,
   url: "https://api.grants.gov/v1/api/search2", params: {keyword: "reinforcement learning", rows: 50}}
- {id: sbir-topics, name: "SBIR.gov open topics", category: gov_solicitation, kind: html_list,
   url: "https://www.sbir.gov/topics?status=1", params: {link_selector: 'a[href^="/topics/"]', max_items: 40}}
```
Then locate and verify (use WebFetch/`curl` to inspect page structure and pick selectors): ARPA-H open funding opportunities, UK ARIA opportunity spaces / funding calls, EU Funding & Tenders (only if a static page or public JSON is found), DrivenData competitions, AIcrowd challenges, HeroX challenges, Zindi competitions, Kaggle competitions, Adaptyv protein-design competitions. JavaScript-rendered pages that return no links to `sources check` are recorded as unreachable (a headless-browser kind is out of v1 scope).

Tier B (`job_board`, all with `params.title_include` = the `discovery.job_title_include` regex from `config.yaml`): probe each company on all three ATS endpoints (`boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true`, `api.lever.co/v0/postings/<token>?mode=json`, `api.ashbyhq.com/posting-api/job-board/<token>`) and keep the one that answers. Target ~30 companies across: AI labs (Anthropic, OpenAI, Google DeepMind, Cohere, Mistral), protein/biotech ML (Isomorphic Labs, Generate Biomedicines, Recursion, Insitro, Absci, Cradle, EvolutionaryScale, Profluent), sequential decision-making / operations / energy / quant (Waymo, Aurora, Nuro, Instacart, DoorDash, Flexport, Octopus Energy, Jane Street, Hudson River Trading, Two Sigma, Citadel Securities), applied ML platforms (Databricks, Scale AI, Palantir). Record which token/ATS worked; unreachable → report.

Tier B (`investor_thesis`): `{id: yc-rfs, name: "YC Requests for Startups", category: investor_thesis, kind: page, url: "https://www.ycombinator.com/rfs"}` (add `content_selector` if the check shows boilerplate dominates).

Tier C (`tech_blog`, kind `rss`): verify ~25 feeds, e.g. `https://netflixtechblog.com/feed`, `https://engineering.fb.com/feed/`, `https://engineering.atspotify.com/feed/`, `https://careersatdoordash.com/engineering-blog/feed/`, `https://medium.com/feed/airbnb-engineering`, `https://www.uber.com/blog/engineering/rss/`, `https://blog.research.google/feeds/posts/default`, `https://www.amazon.science/index.rss`, `https://deepmind.google/blog/rss.xml`, `https://openai.com/news/rss.xml`, `https://huggingface.co/blog/feed.xml`, `https://www.databricks.com/feed`, `https://blog.cloudflare.com/rss/`, `https://tech.instacart.com/feed`, `https://stripe.com/blog/feed.rss`; fill to ~25 with verified feeds from the same kinds of organisations (incl. biotech/protein and operations-research companies).

Tier C (`conference_workshop`, kind `page` or `html_list`): the current-cycle pages (search the web for the 2026/2027 editions) of the KDD Applied Data Science track call, the NeurIPS workshop list, ICML workshop list, RecSys industry track, and AAAI/ICAPS workshop calls on planning / RL applications.

- [ ] **Step 2: Write the live test** `SourceScout/tests/test_live.py`:

```python
import os

import pytest

from conftest import make_registry
from sourcescout.config import load_config
from sourcescout.extract import ExtractContext, make_client, run_extraction
from sourcescout.http import Fetcher
from sourcescout.report import RunReport
from sourcescout.scan import scan
from sourcescout.store import Store
from sourcescout.timeutil import utcnow

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_grants_gov_extraction_within_budget(paths):
    cfg = load_config(paths.config)
    reg = make_registry(paths, [{"id": "grants-gov-ml", "name": "g", "category": "gov_solicitation", "kind": "grants_gov",
                                 "url": "https://api.grants.gov/v1/api/search2",
                                 "params": {"keyword": "machine learning", "rows": 3}}])
    store, now = Store(paths.db), utcnow()
    report = RunReport.new(now)
    scan(reg, store, Fetcher(cfg.http), report, now=now, max_item_chars=cfg.extraction.max_item_chars, force=True)
    assert report.scan["grants-gov-ml"].new >= 1, report.scan
    ctx = ExtractContext(cfg.extraction, reg, store, report, paths.output, report.run_id)
    run_extraction(ctx, make_client(), batch=False, limit=3)
    print(report.render(cfg.extraction.token_budget_per_candidate))
    st = report.extract["grants-gov-ml"]
    assert st.failed == 0, report.failures
    assert st.candidates >= 1
    assert st.tokens_per_candidate() <= cfg.extraction.token_budget_per_candidate
```

- [ ] **Step 3: Run the live test** (requires the user's key)

Run: `ANTHROPIC_API_KEY=... uv run pytest -m live -s SourceScout/tests/test_live.py`
Expected: PASS and a printed report. If `tokens/cand` exceeds 500, report the measured number to the user — do not raise the budget or loosen the assertion. If `cache_rd` is 0, report that the system prompt is below the model's minimum cacheable prefix (expected for a ~700-token prompt); do not pad the prompt to force caching.

- [ ] **Step 4: First real run**

Run: `uv run sourcescout run --limit 20` then inspect `uv run sourcescout report` and 3–5 files in `SourceScout/output/`.
Expected: candidates with `evidence_verified: true` for most records; budget line reported.

- [ ] **Step 5: Run the full suite and commit**

```bash
uv run pytest SourceScout/tests -v
git add SourceScout/registry.yaml SourceScout/tests/test_live.py SourceScout/output && git commit -m "feat: seed registry (verified sources) and live extraction test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
List the dropped/unreachable seeds with reasons in the final report to the user.
