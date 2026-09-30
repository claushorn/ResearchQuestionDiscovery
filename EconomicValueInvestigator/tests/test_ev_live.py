"""Live: one real assessment through the Claude subscription (claude -p with web tools)."""
import shutil
from pathlib import Path

import pytest

from ev_testing import problem, source
from economicvalue.assess import EVContext, assess
from economicvalue.config import EVPaths, load_config
from rqd.claude_code import make_client
from rqd.http import Fetcher
from rqd.records import YamlStore

pytestmark = pytest.mark.live
EV_ROOT = Path(__file__).resolve().parents[1]


def _estimates(ev: dict) -> list:
    return [ev[k] for k in ("current_cost", "failure_cost", "potential_value")]


def test_live_assessment_has_no_amount_without_a_basis(tmp_path):
    root = tmp_path / "EconomicValueInvestigator"
    root.mkdir()
    shutil.copy(EV_ROOT / "config.yaml", root / "config.yaml")
    rec = problem("prob-pi", sources=[source("greenhouse-acme", "B", "hiring", "$180,000 — $250,000 USD")],
                  statement="Detect and block prompt-injection attacks against LLM agents that act on enterprise "
                            "data and tools, without breaking legitimate workflows.")
    YamlStore(tmp_path / "ProblemExtractor" / "problems").save(rec, "prob-pi")
    paths = EVPaths(root)
    cfg = load_config(paths.config)
    ctx = EVContext.open(paths, cfg, make_client("claude_code"), Fetcher(cfg.http))
    assert assess(ctx, ["prob-pi"]) == {}
    out = ctx.assessments.load("prob-pi")
    ev = out["economic_value"]
    print({k: ev[k] for k in ("beneficiary", "pain", "buyer", "deployment", "urgency")})
    print("potential:", ev["potential_value"], "\nfactors:", out["factors"], "\nwarnings:", out["warnings"])
    print("search:", out["search"], "cost:", out["assessed_with"]["cost_usd_equivalent"], out["assessed_with"]["duration_s"])
    for est in _estimates(ev) + list(out["factors"].values()):
        assert est == "unknown" or est["status"] in ("supported", "assumption_only")
        if est != "unknown":
            assert all(b["type"] == "explicit_assumption" or b["verification"] == "verified" for b in est["basis"])
    assert out["search"]["sufficient"]
