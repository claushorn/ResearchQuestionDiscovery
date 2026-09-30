import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from conftest import make_registry
from sourcescout.config import load_config
from sourcescout.extract import ExtractContext, make_client, run_extraction
from sourcescout.http import Fetcher
from sourcescout.report import RunReport
from sourcescout.scan import scan
from sourcescout.store import Store
from sourcescout.timeutil import utcnow

pytestmark = pytest.mark.live
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_grants_gov_extraction_within_budget(paths):
    cfg = load_config(paths.config)
    reg = make_registry(paths, [{"id": "grants-gov-ml", "name": "g", "category": "gov_solicitation", "kind": "grants_gov",
                                 "url": "https://api.grants.gov/v1/api/search2",
                                 "params": {"keyword": "machine learning", "rows": 3}}])
    store, now = Store(paths.db), utcnow()
    report = RunReport.new(now)
    scan(reg, store, Fetcher(cfg.http), report, now=now, max_item_chars=cfg.extraction.max_item_chars, force=True)
    assert report.scan["grants-gov-ml"].new >= 1, report.scan
    ctx = ExtractContext(cfg.extraction, reg, store, report, paths.output, report.run_id)
    run_extraction(ctx, make_client(), batch=False, limit=3)
    print(report.render(cfg.extraction.token_budget_per_candidate))
    st = report.extract["grants-gov-ml"]
    assert st.failed == 0, report.failures
    assert st.candidates >= 1
    assert st.tokens_per_candidate() <= cfg.extraction.token_budget_per_candidate
