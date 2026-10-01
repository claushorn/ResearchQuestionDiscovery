"""Synthetic stage directories and a Frontend directory pointing at them (tests use synthetic data only)."""
from pathlib import Path

import yaml

STAGES = {"sourcescout": "SourceScout", "problemextractor": "ProblemExtractor", "noveltyinvestigator": "NoveltyInvestigator",
          "economicvalue": "EconomicValueInvestigator", "challengeinvestigator": "ChallengeInvestigator",
          "personalfit": "PersonalFitInvestigator", "opportunitygenerator": "OpportunityGenerator"}


def make_frontend(tmp: Path, port: int = 8765, **overrides) -> Path:
    """<tmp>/Frontend/config.yaml with relative roots to <tmp>/<Stage>; the stage directories are created."""
    root = tmp / "Frontend"
    root.mkdir(parents=True, exist_ok=True)
    for d in STAGES.values():
        (tmp / d).mkdir(exist_ok=True)
    cfg = {"port": port, "page_size": 50, "roots": {k: f"../{v}" for k, v in STAGES.items()}} | overrides
    (root / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return root
