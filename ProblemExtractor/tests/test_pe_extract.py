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


def test_category_filter_picks_company_sources(ctx, tmp_path):
    blog = candidate(0, tier="C", source_id="rss-x")
    blog["source"]["category"] = "tech_blog"
    seed(tmp_path / "SourceScout", [blog, candidate(1, tier="A")])
    client = FakeClient([message(pe_output())])
    run_extraction(ctx(), client, categories=["tech_blog"])
    assert len(client.calls) == 1 and "Call 0" in client.calls[0]["messages"][0]["content"]


def test_unknown_category_is_a_clean_error(ctx, tmp_path):
    from rqd.errors import RqdError
    seed(tmp_path / "SourceScout", [candidate(0)])
    with pytest.raises(RqdError, match="tech_blgo") as e:
        run_extraction(ctx(), FakeClient([]), categories=["tech_blgo"])
    assert "gov_solicitation" in e.value.fix


def test_structured_output_retries_are_counted(ctx, tmp_path):
    seed(tmp_path / "SourceScout", [candidate(0)])
    m = message(pe_output())
    m.num_turns = 3  # claude -p rewrote the structured output once
    pe = ctx()
    run_extraction(pe, FakeClient([m]))
    assert pe.report.retries == 1


def test_pe_uses_high_effort_with_a_higher_reported_limit(ctx, tmp_path):
    seed(tmp_path / "SourceScout", [candidate(0), candidate(1, statement="An unrelated sensor calibration problem.")])
    pe = ctx()
    client = FakeClient([message(pe_output(), output_tokens=1900)])
    run_extraction(pe, client, limit=1)
    assert client.calls[0]["output_config"]["effort"] == "high"
    assert pe.cfg.extraction.token_budget == 2000
    assert "per candidate: 1900" in pe.report.render(2000) and "BUDGET VIOLATION" not in pe.report.render(2000)
    assert "BUDGET VIOLATION (> 1500)" in pe.report.render(1500)
    assert "known_solution_inferred" in client.calls[0]["system"][0]["text"]


def test_merged_candidate_quote_is_verified_and_counted(ctx, tmp_path):
    c0, c1 = candidate(0), candidate(1, statement="Planning long horizons for warehouse robots under uncertainty.")
    seed(tmp_path / "SourceScout", [c0, c1])
    pid = problem_id_for(c0["candidate_id"])
    pe = ctx()
    run_extraction(pe, FakeClient([message(pe_output()), message(pe_output(merge_with=pid, evidence="NOT IN THE DOCUMENT"))]))
    assert pe.report.unverified == 1
    assert pe.problems.load(pid)["merge_log"][1]["extracted"]["unsolvedness"]["evidence_verified"] is False


def test_candidate_from_superseded_item_revision_is_not_extracted(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    from sourcescout.adapters.base import RawItem
    from sourcescout.store import Store
    Store(tmp_path / "SourceScout" / "data" / "scout.db").upsert(
        RawItem(c["source_id"], c["source"]["url"], "t", None, "the page changed", ()), "2026-10-01T00:00:00+00:00", 20000)
    pe = ctx()
    client = FakeClient([])
    run_extraction(pe, client)
    assert client.calls == [] and pe.report.superseded == [c["candidate_id"]]
    assert pe.state.is_processed(c["candidate_id"])  # recorded, so not retried forever


def test_malformed_candidate_file_is_reported_and_run_continues(ctx, tmp_path):
    c = candidate(1)
    seed(tmp_path / "SourceScout", [c])
    (tmp_path / "SourceScout" / "output" / "2026-09" / "cand-broken.yaml").write_text("source_id: x\nitem_id: [unclosed\n")
    pe = ctx()
    run_extraction(pe, FakeClient([message(pe_output())]))
    assert pe.report.new == 1 and any("cand-broken.yaml" in f for f in pe.report.failures)


def test_fallback_model_is_recorded_and_counted(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    m = message(pe_output())
    m.models_used = ["claude-opus-5-5", "claude-opus-5"]  # Claude Code fell back after a classifier stop
    pe = ctx()
    run_extraction(pe, FakeClient([m]))
    assert pe.problems.load(problem_id_for(c["candidate_id"]))["extracted_with"]["answered_by"] == ["claude-opus-5-5", "claude-opus-5"]
    assert pe.report.fallbacks == 1 and "model fallbacks: 1" in pe.report.render(2000)


def test_candidate_of_a_finished_challenge_does_not_become_a_problem(ctx, tmp_path):
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    from sourcescout.store import Store
    Store(tmp_path / "SourceScout" / "data" / "scout.db").mark_finished(c["source"]["url"])
    pe = ctx()
    client = FakeClient([])
    run_extraction(pe, client)
    assert client.calls == [] and pe.report.finished == [c["candidate_id"]] and pe.report.new == 0
    assert pe.state.is_processed(c["candidate_id"])


def test_candidate_ids_process_only_those_in_the_given_order(ctx, tmp_path):
    cs = [candidate(0, tier="A"), candidate(1, tier="C", source_id="rss-x"), candidate(2, tier="A")]
    seed(tmp_path / "SourceScout", cs)
    client = FakeClient([message(pe_output()), message(pe_output(statement="Another problem entirely."))])
    pe = ctx()
    run_extraction(pe, client, candidate_ids=[cs[1]["candidate_id"], cs[0]["candidate_id"]])
    assert [c["messages"][0]["content"].split("<title>")[1][:6] for c in client.calls] == ["Call 1", "Call 0"]
    assert pe.state.is_processed(cs[1]["candidate_id"]) and not pe.state.is_processed(cs[2]["candidate_id"])


def test_unknown_or_processed_candidate_id_is_a_clean_error_before_any_extraction(ctx, tmp_path):
    from rqd.errors import RqdError
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c, candidate(1)])
    client = FakeClient([])
    with pytest.raises(RqdError, match="cand-nope") as e:
        run_extraction(ctx(), client, candidate_ids=[candidate(1)["candidate_id"], "cand-nope"])
    assert e.value.fix and client.calls == []
    run_extraction(ctx(), FakeClient([message(pe_output())]), candidate_ids=[c["candidate_id"]])
    with pytest.raises(RqdError, match="already processed"):
        run_extraction(ctx(), client, candidate_ids=[c["candidate_id"]])


def test_candidate_ids_and_categories_are_mutually_exclusive(ctx, tmp_path):
    from rqd.errors import RqdError
    c = candidate(0)
    seed(tmp_path / "SourceScout", [c])
    with pytest.raises(RqdError, match="--candidate"):
        run_extraction(ctx(), FakeClient([]), categories=["tech_blog"], candidate_ids=[c["candidate_id"]])
