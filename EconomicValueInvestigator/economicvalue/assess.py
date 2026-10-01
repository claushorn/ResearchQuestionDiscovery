"""Paid economic assessment of user-picked problems: one agent session each, then code-side verification and
estimate rules (estimates.py). NoveltyInvestigator's 'solved' verdict blocks assessment unless forced."""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from economicvalue.config import EVConfig, EVPaths
from economicvalue.estimates import build
from economicvalue.prompt import render_input, system_prompt
from economicvalue.schema import EV_SCHEMA, EVOutput
from economicvalue.score import score_problem
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import AgentError, ConfigError, RqdError
from rqd.http import Fetcher
from rqd.investigation import run_agent_logged, run_each, run_info, search_summary, with_history
from rqd.records import YamlStore
from rqd.timeutil import utcnow
from rqd.verify import verify_work

log = logging.getLogger("economicvalue")
TOOLS = ["WebSearch", "WebFetch"]


@dataclass
class EVContext:
    cfg: EVConfig
    paths: EVPaths
    problems: YamlStore        # ProblemExtractor/problems (read-only)
    investigations: YamlStore  # NoveltyInvestigator/investigations (read-only)
    assessments: YamlStore
    client: ClaudeCodeClient
    fetcher: Fetcher
    run_id: str

    @classmethod
    def open(cls, paths: EVPaths, cfg: EVConfig, client: ClaudeCodeClient, fetcher: Fetcher,
             run_id: str | None = None) -> "EVContext":
        return cls(cfg, paths, problems_store(paths, cfg), investigations_store(paths, cfg),
                   YamlStore(paths.assessments), client, fetcher, run_id or utcnow().strftime("%Y%m%dT%H%M%SZ"))


def problems_store(paths: EVPaths, cfg: EVConfig) -> YamlStore:
    directory = (paths.root / cfg.problemextractor_root).resolve() / "problems"
    if not directory.is_dir():
        raise ConfigError(f"problems directory not found: {directory}",
                          fix="Set problemextractor_root in EconomicValueInvestigator/config.yaml")
    return YamlStore(directory)


def investigations_store(paths: EVPaths, cfg: EVConfig) -> YamlStore:
    return YamlStore((paths.root / cfg.noveltyinvestigator_root).resolve() / "investigations")


def gate(problems: YamlStore, investigations: YamlStore, problem_id: str, force: bool) -> str:
    """Pre-spend check on the stores alone: raises RqdError when refused, else the gate result for the record."""
    if not problems.exists(problem_id):
        raise RqdError(f"no problem {problem_id}", fix="See `uv run problemextractor list`")
    if not investigations.exists(problem_id):
        log.warning("%s: not investigated by NoveltyInvestigator; assessing anyway", problem_id)
        return "not_investigated"
    try:
        status = investigations.load(problem_id)["novelty"]["status"]
    except (KeyError, TypeError) as e:
        raise RqdError(f"malformed investigation file for {problem_id} ({e!r})",
                       fix=f"Re-run `noveltyinvestigator investigate {problem_id}` or remove the file") from e
    if status == "solved":
        if not force:
            raise RqdError(f"{problem_id}: NoveltyInvestigator marked it solved",
                           fix="Pick another problem, or pass --force to assess it anyway")
        return "forced"
    return "passed"


def assess_one(ctx: EVContext, problem_id: str, gate_result: str) -> dict:
    cfg, a = ctx.cfg, ctx.cfg.agent
    problem = ctx.problems.load(problem_id)
    score = score_problem(problem, cfg.currency_rates_usd, cfg.default_currency_by_source)
    investigation = ctx.investigations.load(problem_id) if ctx.investigations.exists(problem_id) else None
    res, transcript = run_agent_logged(ctx.client, transcripts_dir=ctx.paths.transcripts, record_id=problem_id,
                                       run_id=ctx.run_id, model=a.model, effort=a.effort,
                                       system=system_prompt(a.min_searches),
                                       user=render_input(problem, score, investigation), schema=EV_SCHEMA,
                                       tools=TOOLS, max_budget_usd=a.max_budget_usd)
    try:
        out = EVOutput.model_validate(res.structured_output)
    except ValidationError as e:
        raise AgentError(f"schema: {e.errors()[:3]}", res.transcript) from e
    verification = [verify_work(ctx.fetcher, e.url, e.quote) for e in out.evidence]
    est = build(out, verification, cfg.currency_rates_usd)
    record = {
        "problem_id": problem_id, "revision": 1, "gate": gate_result,
        "economic_value": {
            "beneficiary": {"type": out.beneficiary_type, "description": out.beneficiary_description},
            "pain": {"score": out.pain_score, "reasoning": out.pain_reasoning},
            "current_cost": est["current_cost"], "failure_cost": est["failure_cost"],
            "potential_value": est["potential_value"], "buyer": out.buyer,
            "deployment": {"assessment": out.deployment, "barriers": out.deployment_barriers},
            "urgency": {"level": out.urgency, "reasoning": out.urgency_reasoning},
            "willingness_to_pay": est["willingness_to_pay"]},
        "questions": {"who_has_problem": out.who_has_problem, "how_frequently": out.how_frequently,
                      "how_expensive": out.how_expensive, "current_practice": out.current_practice,
                      "failure_consequence": out.failure_consequence, "deployment": out.deployment,
                      "buyer": out.buyer},
        "factors": est["factors"],
        "potential_value_models": est["potential_value_models"],
        "evidence": [e.model_dump() | {"verification": v} for e, v in zip(out.evidence, verification)],
        "warnings": est["warnings"],
        "search": search_summary(res.tool_calls, a.min_searches),
        "confidence": out.confidence, "score": score,
        "assessed_with": run_info(res, model=a.model, effort=a.effort, transcript=transcript),
        "history": [],
    }
    record = with_history(ctx.assessments, problem_id, record,
                          keep=("revision", "economic_value", "confidence", "search", "assessed_with"))
    ctx.assessments.save(record, problem_id)
    return record


def assess(ctx: EVContext, problem_ids: list[str], force: bool = False) -> dict[str, str]:
    """Assess each problem; returns {problem_id: error}. Gates are checked for all ids before any spend."""
    gates = {pid: gate(ctx.problems, ctx.investigations, pid, force) for pid in problem_ids}
    def one(pid: str) -> str:
        rec = assess_one(ctx, pid, gates[pid])
        pv = rec["economic_value"]["potential_value"]
        value = pv if pv == "unknown" else f"{pv['low']:,.0f}-{pv['high']:,.0f} USD/year ({pv['status']}, {pv['model']})"
        return f"potential {value}, {sum(len(v) for v in rec['warnings'].values())} warnings"
    return run_each(problem_ids, one, log=log, tag="ev", budget=ctx.cfg.agent.max_budget_usd)
