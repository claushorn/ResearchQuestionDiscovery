from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from rqd.config import Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class ExtractCfg(Strict):
    backend: Literal["api", "claude_code"]
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    max_tokens: int
    token_budget: int
    shortlist_size: int


class PEConfig(Strict):
    extraction: ExtractCfg
    sourcescout_root: str


@dataclass(frozen=True)
class PEPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def problems(self) -> Path:
        return self.root / "problems"

    @property
    def db(self) -> Path:
        return self.root / "data" / "pe.db"

    @property
    def runs(self) -> Path:
        return self.root / "data" / "runs"


def load_config(path: Path) -> PEConfig:
    data = load_yaml(path, ConfigError)
    try:
        return PEConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
