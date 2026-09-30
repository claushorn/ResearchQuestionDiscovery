from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from rqd.config import HttpCfg, Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class AgentCfg(Strict):
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    max_budget_usd: float
    min_searches: int


class NIConfig(Strict):
    agent: AgentCfg
    http: HttpCfg
    problemextractor_root: str


@dataclass(frozen=True)
class NIPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def investigations(self) -> Path:
        return self.root / "investigations"

    @property
    def transcripts(self) -> Path:
        return self.root / "data" / "transcripts"


def load_config(path: Path) -> NIConfig:
    data = load_yaml(path, ConfigError)
    try:
        return NIConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
