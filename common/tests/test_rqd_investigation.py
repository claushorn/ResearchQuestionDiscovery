
import pytest

from rqd.claude_code import ClaudeCodeClient, ToolCall
from rqd.errors import AgentError
from rqd.investigation import run_agent_logged, run_info, search_summary, with_history
from rqd.records import YamlStore
from rqd_testing import FakeRunner, agent_result, stream, tool_use

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}




def kw():
    return dict(model="m", effort="medium", system="S", user="U", schema=SCHEMA, tools=["WebSearch"], max_budget_usd=1.0)


def test_run_agent_logged_saves_transcript(tmp_path):
    out = stream(tool_use("WebSearch", query="q"), agent_result(structured_output={}))
    res, name = run_agent_logged(ClaudeCodeClient(runner=FakeRunner(out)), transcripts_dir=tmp_path, record_id="p1",
                                 run_id="R", **kw())
    assert name == "p1-R.jsonl" and (tmp_path / name).read_text() == out and res.structured_output == {}


def test_run_agent_logged_keeps_transcript_of_failed_session(tmp_path):
    out = stream(agent_result(subtype="error_max_budget_usd", is_error=True, terminal_reason="budget_exhausted",
                              structured_output=None, errors=["Reached maximum budget"]))
    with pytest.raises(AgentError):
        run_agent_logged(ClaudeCodeClient(runner=FakeRunner(out, code=1)), transcripts_dir=tmp_path, record_id="p1", run_id="R", **kw())
    assert (tmp_path / "p1-R.jsonl").exists()


def test_search_summary_counts_tool_calls():
    calls = [ToolCall("WebSearch", {"query": "a"}), ToolCall("WebFetch", {"url": "u"}), ToolCall("WebSearch", {"query": "b"})]
    assert search_summary(calls, min_searches=3) == {"searches": 2, "fetches": 1, "queries": ["a", "b"], "sufficient": False}


def test_run_info_and_history(tmp_path):
    out = stream(agent_result(structured_output={}, modelUsage={"m": {}, "m2": {}}))
    res = ClaudeCodeClient(runner=FakeRunner(out)).run_agent(**kw())
    info = run_info(res, model="m", effort="medium", transcript="t.jsonl")
    assert info["answered_by"] == ["m", "m2"] and info["turns"] == 5 and info["transcript"] == "t.jsonl"
    assert info["input_tokens"] == 2 + 900 + 10036 and info["cost_usd_equivalent"] == pytest.approx(0.1257)
    store = YamlStore(tmp_path)
    first = with_history(store, "p1", {"revision": 1, "verdict": "a", "history": []}, keep=("revision", "verdict"))
    store.save(first, "p1")
    second = with_history(store, "p1", {"revision": 1, "verdict": "b", "history": []}, keep=("revision", "verdict"))
    assert second["revision"] == 2 and second["history"] == [{"revision": 1, "verdict": "a"}]


def test_run_each_continues_after_agent_errors_and_stops_on_config_errors():
    import logging
    from rqd.errors import ExtractionConfigError
    from rqd.investigation import run_each

    def fn(rid):
        if rid == "bad":
            raise AgentError("budget exhausted")
        if rid == "limit":
            raise ExtractionConfigError("usage limit")
        return "ok"
    log = logging.getLogger("t")
    assert run_each(["a", "bad", "b"], fn, log=log, tag="x", budget=1.0) == {"bad": "budget exhausted"}
    with pytest.raises(ExtractionConfigError):
        run_each(["a", "limit", "b"], fn, log=log, tag="x", budget=1.0)
