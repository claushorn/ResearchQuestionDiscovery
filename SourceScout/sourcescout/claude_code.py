"""Extraction transport through the local Claude Code CLI (`claude -p`), billed to the user's Claude
subscription instead of the API account. Exposes the same `messages.create(**params)` surface as
`anthropic.Anthropic`, so extraction keeps one response-handling path (extract.handle_message)."""
import json
import os
import subprocess
import tempfile
from types import SimpleNamespace

from sourcescout.errors import ExtractionConfigError, ItemExtractionError

_API_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")  # would silently switch billing to the API account
TIMEOUT_S = 600


class _Messages:
    def __init__(self, runner):
        self._runner = runner

    def create(self, *, model, system, output_config, messages, **_unused) -> SimpleNamespace:
        # max_tokens has no CLI equivalent; the output budget is measured and reported per candidate.
        args = ["claude", "-p", "--safe-mode",  # safe mode: no CLAUDE.md, hooks, skills or plugins in context
                "--model", model, "--effort", output_config["effort"], "--output-format", "json",
                "--tools", "", "--system-prompt", system[0]["text"],
                "--json-schema", json.dumps(output_config["format"]["schema"])]
        env = {k: v for k, v in os.environ.items() if k not in _API_ENV}
        try:
            proc = self._runner(args, input=messages[0]["content"], env=env, cwd=tempfile.gettempdir(),
                                timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise ItemExtractionError(f"claude -p timed out after {TIMEOUT_S}s") from e
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise ItemExtractionError(f"claude -p exit {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}") from e
        if out.get("is_error") or out.get("subtype") != "success":
            status, text = out.get("api_error_status"), str(out.get("result") or "")
            if status in (401, 403) or "login" in text.lower():
                raise ExtractionConfigError(f"Claude Code is not authenticated: {text}", fix="Run `claude` and /login")
            if status == 429 or "limit" in text.lower():
                raise ExtractionConfigError(f"Claude subscription usage limit: {text}",
                                            fix="Wait for the limit to reset, then run extract again")
            raise ItemExtractionError(f"claude -p error (status {status}): {text[:300]}")
        if out.get("structured_output") is None:
            raise ItemExtractionError("claude -p returned no structured_output")
        u = out.get("usage") or {}
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(out["structured_output"]))],
            usage=SimpleNamespace(input_tokens=u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
                                  output_tokens=u.get("output_tokens", 0),
                                  cache_read_input_tokens=u.get("cache_read_input_tokens", 0)))


def _run(args, *, input, env, cwd, timeout):
    return subprocess.run(args, input=input, env=env, cwd=cwd, timeout=timeout, capture_output=True, text=True)


class ClaudeCodeClient:
    def __init__(self, runner=_run):
        self.messages = _Messages(runner)
