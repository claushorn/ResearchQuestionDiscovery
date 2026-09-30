from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from sourcescout.config import Strict, load_yaml
from sourcescout.errors import ConfigError


class Category(Strict):
    id: str
    tier: Literal["A", "B", "C", "D", "E"]
    description: str
    enabled: bool


def load_categories(path: Path) -> dict[str, Category]:
    data = load_yaml(path, ConfigError)
    if not isinstance(data, dict) or not isinstance(data.get("categories"), list):
        raise ConfigError(f"{path}: expected a mapping with a 'categories' list",
                          fix="See the category format documented in SourceScout/README.md")
    try:
        cats = [Category.model_validate(c) for c in data["categories"]]
    except ValidationError as e:
        raise ConfigError(f"{path} is invalid:\n{e}", fix=f"Correct the listed fields in {path}") from e
    out: dict[str, Category] = {}
    for c in cats:
        if c.id in out:
            raise ConfigError(f"{path}: duplicate category id {c.id!r}", fix="Category ids must be unique")
        out[c.id] = c
    return out
