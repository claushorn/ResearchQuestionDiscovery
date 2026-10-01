import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from selectolax.parser import HTMLParser

from sourcescout.categories import Category
from rqd.config import Strict, load_yaml
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


log = logging.getLogger("sourcescout")
STATE_FIELDS = ("status", "provenance", "last_scanned", "health", "yield")  # written by the tools, never by hand


def state_path(registry_path: Path) -> Path:
    """Runtime state and discovered sources: git-ignored, so the tracked registry.yaml stays curated config only."""
    return registry_path.parent / "data" / "registry_state.yaml"


_RENAMED = {"skip_link_text": "finished_link_text", "stop_at_heading": "finished_after_heading"}
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
        self.curated = {s.id for s in sources if s.provenance == "seeded"}  # from registry.yaml; others: discovered

    @classmethod
    def load(cls, path: Path, categories: dict[str, Category], kinds: dict[str, tuple[str, ...]]) -> "Registry":
        data = load_yaml(path, RegistryError)
        raw_sources = data.get("sources") if isinstance(data, dict) else None
        if not isinstance(raw_sources, list):
            raise RegistryError(f"{path}: expected a mapping with a 'sources' list", fix=_FIX)
        sp = state_path(path)
        saved = load_yaml(sp, RegistryError) if sp.exists() else {}
        state, discovered = (saved or {}).get("state") or {}, (saved or {}).get("discovered") or []
        if any(isinstance(raw, dict) and set(raw) & set(STATE_FIELDS) for raw in raw_sources):
            log.warning("%s contains runtime state from before it moved to %s; %s. Restore the tracked file with "
                        "`git checkout -- SourceScout/registry.yaml`", path, sp,
                        "that state file now wins" if sp.exists() else "it is migrated on the next save")
        sources, seen = [], set()
        for i, raw in enumerate(list(raw_sources) + list(discovered)):
            sid = raw.get("id", "?") if isinstance(raw, dict) else "?"
            if sid in seen:  # a discovered source still inline in a pre-split registry.yaml
                continue
            try:
                sources.append(Source.model_validate({**raw, **state.get(sid, {})}))
            except (ValidationError, TypeError) as e:
                where = path if i < len(raw_sources) else sp
                raise RegistryError(f"{where}: source #{i} ({sid}) is invalid:\n{e}", fix=_FIX) from e
            seen.add(sid)
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
        for key in ("link_selector", "content_selector"):
            if key in s.params:
                try:
                    HTMLParser("").css(s.params[key])
                except ValueError as e:
                    raise RegistryError(f"source {s.id!r}: invalid CSS selector in {key}: {e}", fix=_FIX) from e
        for old, new in _RENAMED.items():
            if old in s.params:
                raise RegistryError(f"source {s.id!r}: param {old!r} was renamed (finished items are now flagged, not skipped)",
                                    fix=f"Rename {old} to {new} in registry.yaml")
        for key in ("title_include", "title_exclude", "link_pattern", "finished_link_text", "finished_after_heading"):
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
        """Writes the runtime state of every source and the discovered sources; never the tracked registry.yaml."""
        dumps = {s.id: s.model_dump(by_alias=True) for s in self.sources}
        data = {"state": {sid: {k: d[k] for k in STATE_FIELDS} for sid, d in dumps.items()},
                "discovered": [d for sid, d in dumps.items() if sid not in self.curated]}
        sp = state_path(self.path)
        sp.parent.mkdir(parents=True, exist_ok=True)
        tmp = sp.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(tmp, sp)
