import os
from pathlib import Path

import yaml


class YamlStore:
    """One YAML file per record, named <id>.yaml, written atomically (problems, investigations)."""

    def __init__(self, directory: Path):
        self.dir = directory

    def path(self, record_id: str) -> Path:
        return self.dir / f"{record_id}.yaml"

    def exists(self, record_id: str) -> bool:
        return self.path(record_id).exists()

    def load(self, record_id: str) -> dict:
        return yaml.safe_load(self.path(record_id).read_text(encoding="utf-8"))

    def save(self, record: dict, record_id: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path(record_id)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(tmp, path)

    def all(self) -> list[dict]:
        return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(self.dir.glob("*.yaml"))]
