from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from rqd.config import Strict, load_yaml
from rqd.errors import ConfigError

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class Roots(Strict):
    """Stage directories, relative to the Frontend directory (or absolute)."""
    sourcescout: str
    problemextractor: str
    noveltyinvestigator: str
    economicvalue: str
    challengeinvestigator: str
    personalfit: str
    opportunitygenerator: str


class FEConfig(Strict):
    host: Literal["127.0.0.1"] = "127.0.0.1"   # local only: no login, so never reachable from the network
    port: int
    page_size: int
    roots: Roots

    def stage_roots(self, base: Path) -> dict[str, Path]:
        """Resolved stage directories; a missing one is a configuration error."""
        out = {}
        for name, rel in self.roots.model_dump().items():
            d = (base / rel).resolve()
            if not d.is_dir():
                raise ConfigError(f"stage directory not found: {d}",
                                  fix=f"Set roots.{name} in {base / 'config.yaml'}")
            out[name] = d
        return out


def load_config(path: Path) -> FEConfig:
    data = load_yaml(path, ConfigError)
    try:
        return FEConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
