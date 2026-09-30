import shutil
from pathlib import Path

import pytest

from pe_testing import FakeClient, candidate, message, pe_output, seed
from problemextractor.config import PEPaths, load_config
from problemextractor.extract import PEContext, run_extraction
from problemextractor.records import problem_id_for
from rqd.errors import ItemExtractionError

PE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "ProblemExtractor"
    root.mkdir()
    shutil.copy(PE_ROOT / "config.yaml", root / "config.yaml")
    (tmp_path / "SourceScout").mkdir()
    return lambda: PEContext.open(PEPaths(root), load_config(root / "config.yaml"), run_id="RUN1")


def test_new_problem_written_and_candidate_marked_processed(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    pe = ctx()
    run_extraction(pe, FakeClient([message(pe_output())]))
    rec = pe.problems.load(problem_id_for(c["candidate_id"]))
    assert rec["unsolvedness"]["evidence_verified"] is True and rec["sources"][0]["tier"] == "A"
    assert (pe.report.processed, pe.report.new, pe.report.merged, pe.report.output_tokens) == (1, 1, 0, 420)
    assert pe.state.is_processed(c["candidate_id"])


def test_similar_candidate_merged_via_shortlist(ctx, tmp_path):
    c0, c1 = candidate(0), candidate(1, statement="Planning long horizons for warehouse robots under uncertainty.")
    seed(tmp_path / "SourceScout", [c0, c1])
    pid = problem_id_for(c0["candidate_id"])
    client = FakeClient([message(pe_output()), message(pe_output(merge_with=pid))])
    pe = ctx()
    run_extraction(pe, client)
    assert f"[{pid}]" in client.calls[1]["messages"][0]["content"]
    rec = pe.problems.load(pid)
    assert rec["revision"] == 2 and len(rec["sources"]) == 2 and pe.report.merged == 1
    assert not pe.problems.exists(problem_id_for(c1["candidate_id"]))


def test_merge_with_outside_shortlist_becomes_new_and_is_reported(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    pe = ctx()
    run_extraction(pe, FakeClient([message(pe_output(merge_with="prob-invented"))]))
    assert pe.problems.exists(problem_id_for(c["candidate_id"])) and pe.report.new == 1
    assert pe.report.invalid_merges == [f"{c['candidate_id']}: prob-invented"]


def test_unverifiable_explicit_quote_is_flagged(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    pe = ctx()
    run_extraction(pe, FakeClient([message(pe_output(evidence="a quote that is not in the document"))]))
    assert pe.problems.load(problem_id_for(c["candidate_id"]))["unsolvedness"]["evidence_verified"] is False
    assert pe.report.unverified == 1


def test_rerun_processes_nothing(ctx, tmp_path):
    seed(tmp_path / "SourceScout", [candidate(0)])
    run_extraction(ctx(), FakeClient([message(pe_output())]))
    again = ctx()
    client = FakeClient([])
    run_extraction(again, client)
    assert client.calls == [] and again.report.processed == 0


def test_failed_candidate_is_retried_next_run(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    first = ctx()
    run_extraction(first, FakeClient([ItemExtractionError("claude -p timed out")]))
    assert first.report.failures and not first.state.is_processed(c["candidate_id"])
    second = ctx()
    run_extraction(second, FakeClient([message(pe_output())]))
    assert second.report.new == 1


def test_missing_source_item_is_a_reported_failure(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [])
    out = tmp_path / "SourceScout" / "output" / "2026-09"
    import yaml
    (out / f"{c['candidate_id']}.yaml").write_text(yaml.safe_dump(c))
    pe = ctx()
    run_extraction(pe, FakeClient([]))
    assert "not in the SourceScout store" in pe.report.failures[0]


def test_tier_a_first_and_limit(ctx, tmp_path):
    blog = candidate(0, tier="C", source_id="rss-x", at="2026-09-29T00:00:00+00:00")
    grant = candidate(1, tier="A", at="2026-09-30T00:00:00+00:00")
    seed(tmp_path / "SourceScout", [blog, grant])
    client = FakeClient([message(pe_output())])
    run_extraction(ctx(), client, limit=1)
    assert "Call 1" in client.calls[0]["messages"][0]["content"]
