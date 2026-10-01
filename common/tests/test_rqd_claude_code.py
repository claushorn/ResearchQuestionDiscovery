"""Agent mode of rqd.claude_code, tested against the stream-json shapes recorded from claude 2.1.285."""
import json

import pytest

from rqd.claude_code import ClaudeCodeClient
from rqd.errors import AgentError, ExtractionConfigError
from rqd_testing import FakeRunner, agent_result as result, stream, tool_use

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}




def run(runner):
    return ClaudeCodeClient(runner=runner).run_agent(model="claude-opus-5-5", effort="medium", system="SYS",
                                                     user="problem text", schema=SCHEMA,
                                                     tools=["WebSearch", "WebFetch"], max_budget_usd=2.0)


def test_agent_args_isolated_budgeted_and_key_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    r = FakeRunner(stream(result()))
    run(r)
    a = r.calls[0]["args"]
    assert a[:3] == ["claude", "-p", "--safe-mode"]
    assert a[a.index("--tools") + 1] == "WebSearch,WebFetch" and a[a.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert a[a.index("--output-format") + 1] == "stream-json" and "--verbose" in a
    assert a[a.index("--max-budget-usd") + 1] == "2.0" and a[a.index("--effort") + 1] == "medium"
    assert json.loads(a[a.index("--json-schema") + 1]) == SCHEMA and r.calls[0]["input"] == "problem text"
    assert "ANTHROPIC_API_KEY" not in r.calls[0]["env"]


def test_tool_calls_counted_from_events_not_usage_counter():
    out = stream(tool_use("WebSearch", query="q1"), tool_use("WebSearch", query="q2"),
                 tool_use("WebFetch", url="https://arxiv.org/abs/1"), tool_use("StructuredOutput", a="x"), result())
    res = run(FakeRunner(out))
    assert [(c.name, c.input.get("query") or c.input.get("url")) for c in res.tool_calls] == [
        ("WebSearch", "q1"), ("WebSearch", "q2"), ("WebFetch", "https://arxiv.org/abs/1"), ("StructuredOutput", None)]
    assert res.structured_output == {"a": "x"} and res.num_turns == 5 and res.cost_usd == pytest.approx(0.1257)
    assert res.usage["output_tokens"] == 1608 and res.duration_s == pytest.approx(26.044)
    assert res.transcript == out


def test_budget_exhausted_is_agent_error_with_transcript():
    out = stream(tool_use("WebSearch", query="q"), result(subtype="error_max_budget_usd", is_error=True,
                 terminal_reason="budget_exhausted", structured_output=None, errors=["Reached maximum budget ($0.02)"]))
    with pytest.raises(AgentError, match="budget") as e:
        run(FakeRunner(out, code=1))
    assert e.value.transcript == out


@pytest.mark.parametrize("status, text", [(429, "Claude AI usage limit reached"), (401, "Please run /login")])
def test_usage_limit_and_auth_stop(status, text):
    with pytest.raises(ExtractionConfigError):
        run(FakeRunner(stream(result(is_error=True, subtype="error_during_execution", api_error_status=status,
                                 result=text, structured_output=None)), code=1))


def test_missing_result_line_is_agent_error():
    with pytest.raises(AgentError, match="no result"):
        run(FakeRunner(stream(tool_use("WebSearch", query="q")), code=1))


def test_models_that_actually_answered_are_exposed():
    out = stream(result(modelUsage={"claude-opus-5-5": {}, "claude-opus-5": {}}))
    assert run(FakeRunner(out)).models_used == ["claude-opus-5-5", "claude-opus-5"]


def test_structured_call_exposes_models_used():
    one = json.dumps(result(modelUsage={"claude-opus-5-5": {}, "claude-opus-5": {}}))
    msg = ClaudeCodeClient(runner=FakeRunner(one)).messages.create(
        model="claude-opus-5-5", system=[{"text": "S"}], output_config={"effort": "low", "format": {"schema": SCHEMA}},
        messages=[{"content": "u"}])
    assert msg.models_used == ["claude-opus-5-5", "claude-opus-5"]


def _structured(tid, inp):
    return {"type": "assistant", "message": {"model": "claude-opus-5", "content": [
        {"type": "tool_use", "id": tid, "name": "StructuredOutput", "input": inp}]}}


def _tool_result(tid, text):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


OVER = dict(subtype="error_max_budget_usd", is_error=True, terminal_reason="budget_exhausted", structured_output=None,
            errors=["Reached maximum budget ($0.5)"], total_cost_usd=0.71)


def test_over_budget_session_keeps_an_accepted_structured_output():
    # measured 2026-10-01: a biology-classifier fallback re-read the cached profile on another model, the valid
    # StructuredOutput was accepted ("provided successfully"), then the CLI reported the budget error without it
    out = stream(_structured("t1", {"__unparsedToolInput": "{\"a\": "}),
                 _tool_result("t1", "<tool_use_error>InputValidationError: could not be parsed as JSON</tool_use_error>"),
                 _structured("t2", {"a": "kept"}), _tool_result("t2", "Structured output provided successfully"),
                 result(**OVER))
    res = run(FakeRunner(out, code=1))
    assert res.structured_output == {"a": "kept"} and res.over_budget and res.cost_usd == pytest.approx(0.71)


def test_over_budget_without_an_accepted_output_still_fails():
    out = stream(_structured("t1", {"a": "rejected"}),
                 _tool_result("t1", "Output does not match required schema: root: must have required property 'b'"),
                 result(**OVER))
    with pytest.raises(AgentError, match="budget"):
        run(FakeRunner(out, code=1))
