from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from rqd.config import HttpCfg, Strict, load_yaml
from rqd.errors import ConfigError


class ExtractionCfg(Strict):
    backend: Literal["api", "claude_code"]
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


def load_config(path: Path) -> Config:
    data = load_yaml(path, ConfigError)
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
