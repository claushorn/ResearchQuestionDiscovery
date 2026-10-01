"""LLM calls through the local Claude Code CLI (`claude -p`), billed to the user's Claude subscription.

- `messages.create(**params)`: one structured call, same surface as `anthropic.Anthropic` (SourceScout, PE).
- `run_agent(...)`: a tool-using session (e.g. WebSearch/WebFetch) with a budget cap; tool calls are
  read from the stream-json events, because the result's `server_tool_use` counter reports 0 for them.
"""
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from types import SimpleNamespace

import anthropic
from pydantic import BaseModel, ValidationError

from rqd.errors import AgentError, ExtractionConfigError, ItemExtractionError

_API_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")  # would silently switch billing to the API account
TIMEOUT_S = 600
AGENT_TIMEOUT_S = 1800


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict


@dataclass
class AgentResult:
    structured_output: dict
    tool_calls: list[ToolCall]
    usage: dict
    cost_usd: float
    num_turns: int
    duration_s: float
    models_used: list[str]  # more than one: Claude Code fell back (e.g. after a biology-classifier stop)
    transcript: str = field(repr=False)
    over_budget: bool = False  # the output was accepted, then the session ran past its budget cap


def _accepted_output(events: list[dict]) -> dict | None:
    """The last StructuredOutput the CLI accepted ("provided successfully"), read from the stream. The result event
    of an over-budget session omits it although it was delivered (the cap is checked between turns)."""
    accepted = {b.get("tool_use_id") for e in events if e.get("type") == "user"
                for b in (e.get("message") or {}).get("content") or [] if isinstance(b, dict)
                and b.get("type") == "tool_result" and "provided successfully" in str(b.get("content"))}
    outputs = [b.get("input") for e in events if e.get("type") == "assistant"
               for b in (e.get("message") or {}).get("content") or []
               if b.get("type") == "tool_use" and b.get("name") == "StructuredOutput" and b.get("id") in accepted]
    return outputs[-1] if outputs else None


def _run(args, *, input, env, cwd, timeout):
    return subprocess.run(args, input=input, env=env, cwd=cwd, timeout=timeout, capture_output=True, text=True)


def _args(*, model, effort, system, schema, tools, output_format) -> list[str]:
    args = ["claude", "-p", "--safe-mode",  # safe mode: no CLAUDE.md, hooks, skills or plugins in context
            "--model", model, "--effort", effort, "--output-format", output_format,
            "--tools", ",".join(tools), "--system-prompt", system, "--json-schema", json.dumps(schema)]
    if tools:
        args += ["--allowedTools", ",".join(tools)]
    if output_format == "stream-json":
        args.append("--verbose")
    return args


def _raise_for_error(out: dict, transcript: str = "") -> None:
    """Auth/usage-limit problems stop the whole command; anything else fails this one call."""
    if not (out.get("is_error") or out.get("subtype") != "success"):
        return
    status = out.get("api_error_status")
    text = str(out.get("result") or "; ".join(out.get("errors") or []) or out.get("subtype"))
    if status in (401, 403) or "login" in text.lower():
        raise ExtractionConfigError(f"Claude Code is not authenticated: {text}", fix="Run `claude` and /login")
    if status == 429 or "usage limit" in text.lower():
        raise ExtractionConfigError(f"Claude subscription usage limit: {text}",
                                    fix="Wait for the limit to reset, then run again")
    if "budget" in str(out.get("subtype")) or "budget" in str(out.get("terminal_reason")):
        raise AgentError(f"agent stopped: budget exhausted ({text}; spent ${out.get('total_cost_usd') or 0:.2f})",
                         transcript)
    raise AgentError(f"claude -p error (status {status}): {text[:300]}", transcript)


class _Messages:
    def __init__(self, client: "ClaudeCodeClient"):
        self._client = client

    def create(self, *, model, system, output_config, messages, **_unused) -> SimpleNamespace:
        # max_tokens has no CLI equivalent; the output budget is measured and reported per candidate.
        args = _args(model=model, effort=output_config["effort"], system=system[0]["text"],
                     schema=output_config["format"]["schema"], tools=[], output_format="json")
        proc = self._client._call(args, messages[0]["content"], TIMEOUT_S)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise ItemExtractionError(f"claude -p exit {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}") from e
        _raise_for_error(out)
        if out.get("structured_output") is None:
            raise ItemExtractionError("claude -p returned no structured_output")
        u = out.get("usage") or {}
        return SimpleNamespace(
            stop_reason="end_turn",
            num_turns=out.get("num_turns") or 0,  # > 2: the structured output was rejected and rewritten
            models_used=list(out.get("modelUsage") or {}),  # which models actually answered (fallbacks included)
            content=[SimpleNamespace(type="text", text=json.dumps(out["structured_output"]))],
            usage=SimpleNamespace(input_tokens=u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
                                  output_tokens=u.get("output_tokens", 0),
                                  cache_read_input_tokens=u.get("cache_read_input_tokens", 0)))


class ClaudeCodeClient:
    def __init__(self, runner=_run):
        self._runner = runner
        self.messages = _Messages(self)

    def _call(self, args: list[str], stdin: str, timeout: int) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in _API_ENV}
        try:
            return self._runner(args, input=stdin, env=env, cwd=tempfile.gettempdir(), timeout=timeout)
        except subprocess.TimeoutExpired as e:
            partial = e.output.decode() if isinstance(e.output, bytes) else (e.output or "")
            raise AgentError(f"claude -p timed out after {timeout}s", partial) from e

    def run_agent(self, *, model: str, effort: str, system: str, user: str, schema: dict, tools: list[str],
                  max_budget_usd: float) -> AgentResult:
        args = _args(model=model, effort=effort, system=system, schema=schema, tools=tools,
                     output_format="stream-json") + ["--max-budget-usd", str(max_budget_usd)]
        proc = self._call(args, user, AGENT_TIMEOUT_S)
        transcript = proc.stdout
        events = []
        for line in transcript.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # non-event output; the full transcript is kept verbatim
        results = [e for e in events if e.get("type") == "result"]
        if not results:
            raise AgentError(f"claude -p exit {proc.returncode}: no result event ({(proc.stderr or '')[:200]})",
                             transcript)
        out = results[-1]
        over_budget = False
        if "budget" in str(out.get("subtype")) and (kept := _accepted_output(events)) is not None:
            out, over_budget = out | {"structured_output": kept}, True  # spent: keep what was delivered
        else:
            _raise_for_error(out, transcript)
        if out.get("structured_output") is None:
            raise AgentError("agent finished without structured_output", transcript)
        calls = [ToolCall(b.get("name", ""), b.get("input") or {}) for e in events if e.get("type") == "assistant"
                 for b in (e.get("message") or {}).get("content") or [] if b.get("type") == "tool_use"]
        return AgentResult(out["structured_output"], calls, out.get("usage") or {}, out.get("total_cost_usd") or 0.0,
                           out.get("num_turns") or 0, (out.get("duration_ms") or 0) / 1000,
                           list(out.get("modelUsage") or {}), transcript, over_budget)


def make_client(backend: str):
    if backend == "claude_code":
        if shutil.which("claude") is None:
            raise ExtractionConfigError("backend claude_code needs the `claude` CLI on PATH",
                                        fix="Install Claude Code, or set extraction.backend: api in config.yaml")
        return ClaudeCodeClient()
    client = anthropic.Anthropic()
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        raise ExtractionConfigError("No Anthropic credentials found",
                                    fix="export ANTHROPIC_API_KEY=... (or run `ant auth login`)")
    return client


def raise_if_not_transient(e: anthropic.APIError) -> None:
    """API errors a retry cannot fix (auth, permission, bad model, bad request) abort the run."""
    if isinstance(e, (anthropic.APIConnectionError, anthropic.RateLimitError)):
        return
    if isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
        return
    raise ExtractionConfigError(f"Anthropic API rejected the request: {e}",
                                fix="Check credentials, the model name in config.yaml, and the request schema") from e


def parse_structured(message, model: type[BaseModel]):
    """Validated structured output of one response (either backend); ItemExtractionError if unusable."""
    if message.stop_reason in ("refusal", "max_tokens"):
        raise ItemExtractionError(f"stop_reason={message.stop_reason}")
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise ItemExtractionError("no text block in response")
    try:
        return model.model_validate_json(text)
    except ValidationError as e:
        raise ItemExtractionError(f"schema: {e.errors()[:3]}") from e
