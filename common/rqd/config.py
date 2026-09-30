from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from rqd.errors import RqdError


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HttpCfg(Strict):
    user_agent: str
    timeout_s: float
    min_interval_s_per_host: float


def load_yaml(path: Path, error_cls: type[RqdError]) -> object:
    if not path.exists():
        raise error_cls(f"{path} not found", fix=f"Create {path.name} in {path.parent}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise error_cls(f"{path} is not valid YAML: {e}", fix=f"Fix the YAML syntax in {path}") from e
