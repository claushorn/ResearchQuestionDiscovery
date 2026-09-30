from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from rqd.config import AgentCfg, HttpCfg, Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class Thresholds(Strict):
    """The recommendation is `ignore` unless every known dimension reaches its threshold (0-10)."""
    fit: int
    tractability: int
    novelty: int
    value: int


class OGConfig(Strict):
    agent: AgentCfg
    profile_name: str   # shown in the brief's "WHY <NAME>?" section
    thresholds: Thresholds
    http: HttpCfg
    problemextractor_root: str
    personalfit_root: str
    noveltyinvestigator_root: str
    economicvalue_root: str


@dataclass(frozen=True)
class OGPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def opportunities(self) -> Path:
        return self.root / "opportunities"

    @property
    def briefs(self) -> Path:
        return self.root / "briefs"

    @property
    def transcripts(self) -> Path:
        return self.root / "data" / "transcripts"


def load_config(path: Path) -> OGConfig:
    data = load_yaml(path, ConfigError)
    try:
        return OGConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
