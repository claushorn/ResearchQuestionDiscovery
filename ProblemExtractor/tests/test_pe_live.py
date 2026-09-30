"""Live: one real extraction through the Claude subscription (claude -p)."""
import shutil
from pathlib import Path

import pytest

from pe_testing import candidate, seed
from problemextractor.config import PEPaths, load_config
from problemextractor.extract import PEContext, run_extraction
from rqd.claude_code import make_client

pytestmark = pytest.mark.live
PE_ROOT = Path(__file__).resolve().parents[1]


def test_real_extraction_adds_labelled_expert_knowledge(tmp_path):
    root = tmp_path / "ProblemExtractor"
    root.mkdir()
    shutil.copy(PE_ROOT / "config.yaml", root / "config.yaml")
    seed(tmp_path / "SourceScout", [candidate(0)])
    cfg = load_config(root / "config.yaml")
    pe = PEContext.open(PEPaths(root), cfg)
    run_extraction(pe, make_client(cfg.extraction.backend))
    print(pe.report.render(cfg.extraction.token_budget))
    assert pe.report.failures == [] and pe.report.new == 1 and pe.report.unverified == 0
    assert pe.report.output_tokens <= cfg.extraction.token_budget * (1 + pe.report.retries)
    rec = pe.problems.all()[0]
    print(rec["current_state"], rec["failure"])
    assert rec["current_state"]["known_solution_inferred"]  # high effort fills the gap the document leaves
