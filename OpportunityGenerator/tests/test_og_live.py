"""Live: one real opportunity from fixture records (run with `-m live`)."""
import shutil
from pathlib import Path

import pytest

from og_testing import fit, problem
from opportunitygenerator.config import OGPaths, load_config
from opportunitygenerator.run import OGContext, generate
from rqd.claude_code import make_client
from rqd.http import Fetcher
from rqd.records import YamlStore

pytestmark = pytest.mark.live


def test_live_generation_without_novelty_or_ev(tmp_path):
    root = tmp_path / "OpportunityGenerator"
    root.mkdir()
    shutil.copy(Path(__file__).resolve().parents[1] / "config.yaml", root / "config.yaml")
    YamlStore(tmp_path / "ProblemExtractor" / "problems").save(problem(), "prob-a")
    YamlStore(tmp_path / "PersonalFitInvestigator" / "fits").save(fit(), "prob-a")
    paths = OGPaths(root)
    cfg = load_config(paths.config)
    ctx = OGContext.open(paths, cfg, make_client("claude_code"), Fetcher(cfg.http))
    assert generate(ctx, ["prob-a"]) == {}
    rec = ctx.stores.opportunities.load("OPP-0001")
    assert rec["opportunity_profile"]["novelty"] is None and rec["opportunity_profile"]["economic_value"] is None
    assert "not checked: run noveltyinvestigator" in (paths.briefs / "OPP-0001.md").read_text()
