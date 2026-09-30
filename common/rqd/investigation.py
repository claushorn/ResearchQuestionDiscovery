"""Scaffolding shared by agent-based investigators (NoveltyInvestigator, EconomicValueInvestigator)."""
from pathlib import Path

from rqd.claude_code import AgentResult, ClaudeCodeClient, ToolCall
from rqd.errors import AgentError
from rqd.records import YamlStore
from rqd.timeutil import iso, utcnow


def _save(transcripts_dir: Path, name: str, transcript: str) -> None:
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    (transcripts_dir / name).write_text(transcript, encoding="utf-8")


def run_agent_logged(client: ClaudeCodeClient, *, transcripts_dir: Path, record_id: str, run_id: str,
                     **agent_kwargs) -> tuple[AgentResult, str]:
    """Run one agent session; the transcript is saved for audit whether the session succeeds or fails."""
    name = f"{record_id}-{run_id}.jsonl"
    try:
        res = client.run_agent(**agent_kwargs)
    except AgentError as e:
        if e.transcript:
            _save(transcripts_dir, name, e.transcript)
        raise
    _save(transcripts_dir, name, res.transcript)
    return res, name


def search_summary(tool_calls: list[ToolCall], min_searches: int) -> dict:
    """Counted from the session's tool calls, never self-reported by the model."""
    searches = [c for c in tool_calls if c.name == "WebSearch"]
    return {"searches": len(searches), "fetches": sum(c.name == "WebFetch" for c in tool_calls),
            "queries": [c.input.get("query", "") for c in searches], "sufficient": len(searches) >= min_searches}


def run_info(res: AgentResult, *, model: str, effort: str, transcript: str) -> dict:
    u = res.usage
    return {"model": model, "effort": effort, "cost_usd_equivalent": round(res.cost_usd, 4),
            "output_tokens": u.get("output_tokens", 0),
            "input_tokens": sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                       "cache_read_input_tokens")),
            "turns": res.num_turns, "duration_s": round(res.duration_s, 1), "at": iso(utcnow()),
            "transcript": transcript, "answered_by": res.models_used or [model]}


def with_history(store: YamlStore, record_id: str, record: dict, keep: tuple[str, ...]) -> dict:
    """A re-run bumps the revision and keeps a summary (`keep` keys) of the previous revision."""
    if store.exists(record_id):
        old = store.load(record_id)
        record = {**record, "revision": old["revision"] + 1,
                  "history": old.get("history", []) + [{k: old[k] for k in keep if k in old}]}
    return record
