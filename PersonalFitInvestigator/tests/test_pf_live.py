"""Live: one real fit with a synthetic profile (run with `-m live`)."""
import shutil
from pathlib import Path

import pytest

from pf_testing import make_profile, problem
from personalfit.config import PFPaths, load_config
from personalfit.run import PFContext, assess
from rqd.claude_code import make_client
from rqd.records import YamlStore

pytestmark = pytest.mark.live


def test_live_fit_backs_advantages_with_profile_quotes(tmp_path):
    root = tmp_path / "PersonalFitInvestigator"
    root.mkdir()
    shutil.copy(Path(__file__).resolve().parents[1] / "config.yaml", root / "config.yaml")
    make_profile(tmp_path / "personal_profile")
    YamlStore(tmp_path / "ProblemExtractor" / "problems").save(problem(), "prob-a")
    paths = PFPaths(root)
    ctx = PFContext.open(paths, load_config(paths.config), make_client("claude_code"))
    assert assess(ctx, ["prob-a"]) == {}
    fit = ctx.fits.load("prob-a")
    assert fit["advantages"], fit["warnings"]
    assert all(a["file"] in {"cv.md", "cv_long.pdf", "capabilities.yaml", "interests.yml"} for a in fit["advantages"])
