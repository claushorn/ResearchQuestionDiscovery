from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from rqd.config import AgentCfg, Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class PFConfig(Strict):
    agent: AgentCfg
    profile_dir: str               # relative to the PersonalFitInvestigator directory
    profile_max_chars: int
    self_rating_files: list[str]   # profile files holding self-ratings: never enough on their own
    self_rating_cap: int
    no_advantage_cap: int
    problemextractor_root: str
    noveltyinvestigator_root: str
    economicvalue_root: str


@dataclass(frozen=True)
class PFPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def fits(self) -> Path:
        return self.root / "fits"

    @property
    def transcripts(self) -> Path:
        return self.root / "data" / "transcripts"


def load_config(path: Path) -> PFConfig:
    data = load_yaml(path, ConfigError)
    try:
        return PFConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
