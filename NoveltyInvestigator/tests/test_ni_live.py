"""Live: a real agent session on a problem known to be solved. Uses the Claude subscription (claude -p)."""
import shutil
from pathlib import Path

import pytest

from ni_testing import problem_record
from noveltyinvestigator.config import NIPaths, load_config
from noveltyinvestigator.investigate import NIContext, investigate
from rqd.claude_code import make_client
from rqd.http import Fetcher
from rqd.records import YamlStore

pytestmark = pytest.mark.live
NI_ROOT = Path(__file__).resolve().parents[1]


def test_known_solved_problem_is_killed(tmp_path):
    root = tmp_path / "NoveltyInvestigator"
    root.mkdir()
    shutil.copy(NI_ROOT / "config.yaml", root / "config.yaml")
    rec = problem_record("prob-go")
    rec["problem"]["precise_statement"] = ("Learn to play the board game Go at superhuman level purely from self-play, "
                                           "without human game records or handcrafted features.")
    rec["desired_capability"] = "a Go program that beats top professionals, trained without human data"
    rec["why_it_matters"] = "general reinforcement learning without human data"
    YamlStore(tmp_path / "ProblemExtractor" / "problems").save(rec, "prob-go")
    paths = NIPaths(root)
    cfg = load_config(paths.config)
    ctx = NIContext.open(paths, cfg, make_client("claude_code"), Fetcher(cfg.http))
    assert investigate(ctx, ["prob-go"]) == {}
    out = ctx.investigations.load("prob-go")
    print({k: out[k] for k in ("novelty", "confidence", "search", "verified_fraction", "investigated_with")})
    print([(w["title"], w["url"], w["verification"]) for w in out["closest_work"]])
    assert out["novelty"]["status"] in ("solved", "partially_solved")
    assert out["search"]["sufficient"]
    assert any(w["verification"] == "verified" for w in out["closest_work"])
