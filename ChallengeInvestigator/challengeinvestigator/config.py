from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from rqd.config import AgentCfg, HttpCfg, Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class CIConfig(Strict):
    headroom_agent: AgentCfg
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
