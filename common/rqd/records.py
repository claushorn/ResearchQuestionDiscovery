import os
from pathlib import Path

import yaml


def read_yaml(path: Path) -> object:
    """One YAML file, parsed safely with libyaml (~10x faster than the pure-Python loader: pages read 500+ records)."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.CSafeLoader)


class YamlStore:
    """One YAML file per record, named <id>.yaml, written atomically (problems, investigations)."""

    def __init__(self, directory: Path):
        self.dir = directory

    def path(self, record_id: str) -> Path:
        return self.dir / f"{record_id}.yaml"

    def exists(self, record_id: str) -> bool:
        return self.path(record_id).exists()

    def load(self, record_id: str) -> dict:
        return read_yaml(self.path(record_id))

    def save(self, record: dict, record_id: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path(record_id)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(tmp, path)

    def all(self) -> list[dict]:
        return [read_yaml(p) for p in sorted(self.dir.glob("*.yaml"))]
