import shutil
from pathlib import Path

import pytest

from sourcescout.categories import load_categories
from sourcescout.config import Paths
from sourcescout.registry import Registry, Source

REPO_SCOUT = Path(__file__).resolve().parents[1]


@pytest.fixture
def paths(tmp_path) -> Paths:
    shutil.copy(REPO_SCOUT / "sources.yaml", tmp_path / "sources.yaml")
    shutil.copy(REPO_SCOUT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "registry.yaml").write_text("sources: []\n")
    return Paths(tmp_path)


def make_registry(paths: Paths, sources: list[dict], kinds: dict | None = None) -> Registry:
    if kinds is None:  # default kinds come from the adapters (Task 3)
        from sourcescout.adapters import REQUIRED_PARAMS
        kinds = REQUIRED_PARAMS
    cats = load_categories(paths.categories)
    return Registry(paths.registry, [Source.model_validate(s) for s in sources], cats, kinds)
