from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from rqd.config import AgentCfg, HttpCfg, Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class EVConfig(Strict):
    agent: AgentCfg
    http: HttpCfg
    problemextractor_root: str
    noveltyinvestigator_root: str
    currency_rates_usd: dict[str, float]
    default_currency_by_source: dict[str, str]


@dataclass(frozen=True)
class EVPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def assessments(self) -> Path:
        return self.root / "assessments"

    @property
    def scores(self) -> Path:
        return self.root / "data" / "scores.yaml"

    @property
    def transcripts(self) -> Path:
        return self.root / "data" / "transcripts"


def load_config(path: Path) -> EVConfig:
    data = load_yaml(path, ConfigError)
    try:
        return EVConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
