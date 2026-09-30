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


class ScanCfg(Strict):
    job_title_include: str  # default title filter for job_board sources without their own title_include


class DiscoveryCfg(Strict):
    max_fetches_per_run: int
    ignore_hosts: list[str]


class Config(Strict):
    extraction: ExtractionCfg
    lifecycle: LifecycleCfg
    http: HttpCfg
    scan: ScanCfg
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
