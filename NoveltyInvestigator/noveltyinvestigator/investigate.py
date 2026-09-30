"""Adversarial novelty investigation of user-picked problems: one `claude -p` agent session each, then
deterministic verification of every cited work."""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from noveltyinvestigator.config import NIConfig, NIPaths
from noveltyinvestigator.prompt import render_problem, system_prompt
from noveltyinvestigator.schema import NI_SCHEMA, NIOutput, to_record_fields
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import AgentError, RqdError
from rqd.http import Fetcher
from rqd.investigation import run_agent_logged, run_each, run_info, search_summary, with_history
from rqd.records import YamlStore
from rqd.verify import verify_work
from rqd.timeutil import utcnow

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


def investigate_one(ctx: NIContext, problem_id: str) -> dict:
    problem = ctx.problems.load(problem_id)
    a = ctx.cfg.agent
    res, transcript = run_agent_logged(ctx.client, transcripts_dir=ctx.paths.transcripts, record_id=problem_id,
                                       run_id=ctx.run_id, model=a.model, effort=a.effort,
                                       system=system_prompt(a.min_searches), user=render_problem(problem),
                                       schema=NI_SCHEMA, tools=TOOLS, max_budget_usd=a.max_budget_usd)
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
    record = {
        "problem_id": problem_id, "revision": 1, **fields,
        "search": search_summary(res.tool_calls, a.min_searches),
        "verified_fraction": round(sum(w["verification"] == "verified" for w in works) / len(works), 2) if works else 0.0,
        "investigated_with": run_info(res, model=a.model, effort=a.effort, transcript=transcript),
        "history": [],
    }
    record = with_history(ctx.investigations, problem_id, record,
                          keep=("revision", "novelty", "confidence", "verified_fraction", "search", "investigated_with"))
    ctx.investigations.save(record, problem_id)
    return record


def investigate(ctx: NIContext, problem_ids: list[str]) -> dict[str, str]:
    """Investigate each problem; returns {problem_id: error} for the ones that failed. Auth/usage limits stop the whole command."""
    for pid in problem_ids:
        if not ctx.problems.exists(pid):
            raise RqdError(f"no problem {pid}", fix="See `uv run problemextractor list`")
    def one(pid: str) -> str:
        rec = investigate_one(ctx, pid)
        verified = sum(w["verification"] == "verified" for w in rec["closest_work"])
        return (f"{rec['novelty']['status']} (confidence {rec['confidence']:.2f}), {rec['search']['searches']} searches, "
                f"{verified}/{len(rec['closest_work'])} works verified")
    return run_each(problem_ids, one, log=log, tag="ni", budget=ctx.cfg.agent.max_budget_usd)
