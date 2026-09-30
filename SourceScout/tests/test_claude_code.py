import json
import subprocess

import pytest

from test_extract import add_item, cand, ctx  # noqa: F401  (fixture re-export)
from sourcescout.claude_code import ClaudeCodeClient
from sourcescout.errors import ExtractionConfigError
from sourcescout.extract import build_params, make_client, run_extraction


def result(structured=None, is_error=False, status=None, text="", out_tokens=420):
    return json.dumps({"type": "result", "subtype": "error_during_execution" if is_error else "success",
                       "is_error": is_error, "api_error_status": status, "result": text,
                       "structured_output": structured,
                       "usage": {"input_tokens": 5, "cache_creation_input_tokens": 1000,
                                 "cache_read_input_tokens": 300, "output_tokens": out_tokens}})


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, args, *, input, env, cwd, timeout):
        self.calls.append({"args": args, "input": input, "env": env, "cwd": cwd})
        out = self.outputs.pop(0)
        return subprocess.CompletedProcess(args, 0 if '"is_error": false' in out else 1, stdout=out, stderr="")


def test_invocation_isolated_and_key_stripped(ctx, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    add_item(ctx)
    [item] = ctx.store.pending()
    params = build_params(ctx.cfg, item, ctx.registry.get("g"), ctx.registry.categories["gov_solicitation"])
    runner = FakeRunner([result({"candidates": []})])
    ClaudeCodeClient(runner=runner).messages.create(**params)
    call = runner.calls[0]
    a = call["args"]
    assert a[:3] == ["claude", "-p", "--safe-mode"]
    assert a[a.index("--model") + 1] == "claude-opus-5-5" and a[a.index("--effort") + 1] == "low"
    assert a[a.index("--tools") + 1] == "" and a[a.index("--output-format") + 1] == "json"
    assert a[a.index("--system-prompt") + 1] == params["system"][0]["text"]
    assert json.loads(a[a.index("--json-schema") + 1]) == params["output_config"]["format"]["schema"]
    assert call["input"] == params["messages"][0]["content"]
    assert "ANTHROPIC_API_KEY" not in call["env"]


def test_extraction_through_claude_code_writes_records(ctx):
    add_item(ctx)
    run_extraction(ctx, ClaudeCodeClient(runner=FakeRunner([result({"candidates": [cand()]})])), batch=False)
    st = ctx.report.extract["g"]
    assert (st.candidates, st.output_tokens, st.cache_read_tokens) == (1, 420, 300)
    assert len(list(ctx.output_dir.glob("*/*.yaml"))) == 1


@pytest.mark.parametrize("status, text", [(429, "Claude AI usage limit reached"), (401, "Invalid API key · Please run /login")])
def test_usage_limit_or_auth_aborts(ctx, status, text):
    add_item(ctx)
    with pytest.raises(ExtractionConfigError):
        run_extraction(ctx, ClaudeCodeClient(runner=FakeRunner([result(is_error=True, status=status, text=text)])), batch=False)


def test_other_error_fails_item_and_continues(ctx):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    runner = FakeRunner([result(is_error=True, status=500, text="Overloaded"), result({"candidates": [cand()]})])
    run_extraction(ctx, ClaudeCodeClient(runner=runner), batch=False)
    assert len(ctx.report.failures) == 1 and "Overloaded" in ctx.report.failures[0]["error"]
    assert ctx.report.extract["g"].candidates == 1


def test_batch_requires_api_backend(ctx):
    add_item(ctx)
    with pytest.raises(ExtractionConfigError, match="batch"):
        run_extraction(ctx, ClaudeCodeClient(runner=FakeRunner([])), batch=True)


def test_make_client_claude_code_requires_cli(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ExtractionConfigError, match="claude"):
        make_client(ctx.cfg.model_copy(update={"backend": "claude_code"}))
