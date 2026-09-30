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
