"""Adversarial novelty investigation of user-picked problems: one `claude -p` agent session each, then
deterministic verification of every cited work."""
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from noveltyinvestigator.config import NIConfig, NIPaths
from noveltyinvestigator.prompt import render_problem, system_prompt
from noveltyinvestigator.schema import NI_SCHEMA, NIOutput, to_record_fields
from noveltyinvestigator.verify import verify_work
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import AgentError, RqdError
from rqd.http import Fetcher
from rqd.records import YamlStore
from rqd.timeutil import iso, utcnow

log = logging.getLogger("noveltyinvestigator")
TOOLS = ["WebSearch", "WebFetch"]


@dataclass
class NIContext:
    cfg: NIConfig
    paths: NIPaths
    problems: YamlStore        # ProblemExtractor/problems (read-only)
    investigations: YamlStore  # NoveltyInvestigator/investigations
    client: ClaudeCodeClient
    fetcher: Fetcher
    run_id: str

    @classmethod
    def open(cls, paths: NIPaths, cfg: NIConfig, client: ClaudeCodeClient, fetcher: Fetcher,
             run_id: str | None = None) -> "NIContext":
        problems = YamlStore((paths.root / cfg.problemextractor_root).resolve() / "problems")
        return cls(cfg, paths, problems, YamlStore(paths.investigations), client, fetcher,
                   run_id or utcnow().strftime("%Y%m%dT%H%M%SZ"))


def _save_transcript(ctx: NIContext, problem_id: str, transcript: str) -> str:
    ctx.paths.transcripts.mkdir(parents=True, exist_ok=True)
    name = f"{problem_id}-{ctx.run_id}.jsonl"
    (ctx.paths.transcripts / name).write_text(transcript, encoding="utf-8")
    return name


def investigate_one(ctx: NIContext, problem_id: str) -> dict:
    problem = ctx.problems.load(problem_id)
    a = ctx.cfg.agent
    try:
        res = ctx.client.run_agent(model=a.model, effort=a.effort, system=system_prompt(a.min_searches),
                                   user=render_problem(problem), schema=NI_SCHEMA, tools=TOOLS,
                                   max_budget_usd=a.max_budget_usd)
    except AgentError as e:
        if e.transcript:
            _save_transcript(ctx, problem_id, e.transcript)
        raise
    transcript = _save_transcript(ctx, problem_id, res.transcript)
    try:
        out = NIOutput.model_validate(res.structured_output)
    except ValidationError as e:
        raise AgentError(f"schema: {e.errors()[:3]}", res.transcript) from e
    fields = to_record_fields(out)
    for work in fields["closest_work"]:
        work["verification"] = verify_work(ctx.fetcher, work["url"], work["quote"])
    works = fields["closest_work"]
    for check in fields["checks"].values():  # model-supplied numbers into closest_work (1-based)
        invalid = [n for n in check["evidence"] if not 1 <= n <= len(works)]
        if invalid:
            check["evidence"] = [n for n in check["evidence"] if 1 <= n <= len(works)]
            check["invalid_evidence"] = invalid
    searches = [c for c in res.tool_calls if c.name == "WebSearch"]
    u = res.usage
    record = {
        "problem_id": problem_id, "revision": 1, **fields,
        "search": {"searches": len(searches), "fetches": sum(c.name == "WebFetch" for c in res.tool_calls),
                   "queries": [c.input.get("query", "") for c in searches],
                   "sufficient": len(searches) >= a.min_searches},
        "verified_fraction": round(sum(w["verification"] == "verified" for w in works) / len(works), 2) if works else 0.0,
        "investigated_with": {"model": a.model, "effort": a.effort, "cost_usd_equivalent": round(res.cost_usd, 4),
                              "output_tokens": u.get("output_tokens", 0),
                              "input_tokens": sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                                         "cache_read_input_tokens")),
                              "turns": res.num_turns, "duration_s": round(res.duration_s, 1), "at": iso(utcnow()),
                              "transcript": transcript},
        "history": [],
    }
    if ctx.investigations.exists(problem_id):
        old = ctx.investigations.load(problem_id)
        record["revision"] = old["revision"] + 1
        record["history"] = old["history"] + [{k: old[k] for k in ("revision", "novelty", "confidence",
                                                                     "verified_fraction", "search", "investigated_with")}]
    ctx.investigations.save(record, problem_id)
    return record


def investigate(ctx: NIContext, problem_ids: list[str]) -> dict[str, str]:
    """Investigate each problem; returns {problem_id: error} for the ones that failed. Auth/usage limits stop the whole command."""
    for pid in problem_ids:
        if not ctx.problems.exists(pid):
            raise RqdError(f"no problem {pid}", fix="See `uv run problemextractor list`")
    failures: dict[str, str] = {}
    for i, pid in enumerate(problem_ids, 1):
        log.info("[ni %d/%d] %s: investigating (budget $%.2f) ...", i, len(problem_ids), pid, ctx.cfg.agent.max_budget_usd)
        started = time.monotonic()
        try:
            rec = investigate_one(ctx, pid)
        except AgentError as e:
            failures[pid] = str(e)
            log.warning("[ni %d/%d] %s -> FAILED %s", i, len(problem_ids), pid, str(e)[:200])
            continue
        log.info("[ni %d/%d] %s -> %s (confidence %.2f), %d searches, %d/%d works verified (%.0fs)", i,
                 len(problem_ids), pid, rec["novelty"]["status"], rec["confidence"], rec["search"]["searches"],
                 sum(w["verification"] == "verified" for w in rec["closest_work"]), len(rec["closest_work"]),
                 time.monotonic() - started)
    return failures
