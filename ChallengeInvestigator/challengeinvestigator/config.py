import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError, field_validator

from rqd.config import AgentCfg, HttpCfg, Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class MetricBound(Strict):
    match: str        # regex, searched case-insensitively in the leaderboard's metric name
    direction: Literal["higher_is_better", "lower_is_better"]
    ceiling: float    # the best value the metric's definition allows
    definition: str   # recorded as the ceiling's basis

    @field_validator("match")
    @classmethod
    def _regex(cls, v: str) -> str:
        re.compile(v)
        return v


class CIConfig(Strict):
    leaderboard_sources: dict[str, Literal["aicrowd", "drivendata"]]  # SourceScout source id -> leaderboard scraper
    metric_bounds: list[MetricBound]
    baseline_agent: AgentCfg
    investigate_agent: AgentCfg
    headroom_threshold: float
    http: HttpCfg
    sourcescout_root: str


@dataclass(frozen=True)
class CIPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def challenges(self) -> Path:
        return self.root / "challenges"

    @property
    def transcripts(self) -> Path:
        return self.root / "data" / "transcripts"


def load_config(path: Path) -> CIConfig:
    data = load_yaml(path, ConfigError)
    try:
        return CIConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
