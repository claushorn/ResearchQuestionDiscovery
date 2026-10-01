import shutil
from pathlib import Path

import pytest
import yaml

from sourcescout.categories import load_categories
from rqd_testing import make_fetcher  # noqa: F401  (re-exported for SourceScout tests)
from sourcescout.config import Paths
from sourcescout.registry import STATE_FIELDS, Registry, Source

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
    parsed = [Source.model_validate(s) for s in sources]
    curated = [{k: v for k, v in s.items() if k not in STATE_FIELDS} for s in sources if s.get("provenance", "seeded") == "seeded"]
    paths.registry.write_text(yaml.safe_dump({"sources": curated}, sort_keys=False))  # as the user curates it
    return Registry(paths.registry, parsed, cats, kinds)
