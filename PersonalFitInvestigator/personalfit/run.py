"""Personal fit per problem: one agent call (profile vs problem, no web), then code-side rules (rules.py)."""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from personalfit.config import PFConfig, PFPaths
from personalfit.profile import Profile, load_profile
from personalfit.prompt import render_input, system_prompt
from personalfit.rules import apply
from personalfit.schema import FIT_SCHEMA, FitOutput
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import AgentError, ConfigError, RqdError
from rqd.investigation import run_agent_logged, run_each, run_info, with_history
from rqd.records import YamlStore
from rqd.timeutil import utcnow

log = logging.getLogger("personalfit")


@dataclass
class PFContext:
    cfg: PFConfig
    paths: PFPaths
    profile: Profile
    problems: YamlStore        # ProblemExtractor/problems (read-only)
    investigations: YamlStore  # NoveltyInvestigator/investigations (read-only, optional per problem)
    assessments: YamlStore     # EconomicValueInvestigator/assessments (read-only, optional per problem)
    fits: YamlStore
    client: ClaudeCodeClient
    run_id: str

    @classmethod
    def open(cls, paths: PFPaths, cfg: PFConfig, client: ClaudeCodeClient, run_id: str | None = None) -> "PFContext":
        return cls(cfg, paths, load_profile((paths.root / cfg.profile_dir).resolve(), cfg.profile_max_chars),
                   problems_store(paths, cfg), _store(paths, cfg.noveltyinvestigator_root, "investigations"),
                   _store(paths, cfg.economicvalue_root, "assessments"),
                   YamlStore(paths.fits), client, run_id or utcnow().strftime("%Y%m%dT%H%M%SZ"))

    def optional(self, store: YamlStore, problem_id: str) -> dict | None:
        return store.load(problem_id) if store.exists(problem_id) else None


def _store(paths: PFPaths, root: str, sub: str, required: bool = False) -> YamlStore:
    d = (paths.root / root).resolve() / sub
    if required and not d.is_dir():
        raise ConfigError(f"directory not found: {d}", fix="Set the *_root paths in PersonalFitInvestigator/config.yaml")
    return YamlStore(d)


def problems_store(paths: PFPaths, cfg: PFConfig) -> YamlStore:
    return _store(paths, cfg.problemextractor_root, "problems", required=True)


def refusal(problems: YamlStore, problem_id: str) -> RqdError | None:
    """Pre-spend check of `assess` on the store alone: None = runnable, else the refusal (message and fix)."""
    if not problems.exists(problem_id):
        return RqdError(f"no problem {problem_id}", fix="See `uv run problemextractor list`")
    return None


def is_stale(fit: dict, problem: dict, profile: Profile) -> bool:
    return fit["problem_revision"] != problem["revision"] or fit["profile_digest"] != profile.digest


def assess_one(ctx: PFContext, problem_id: str) -> dict:
    a = ctx.cfg.agent
    problem = ctx.problems.load(problem_id)
    res, transcript = run_agent_logged(
        ctx.client, transcripts_dir=ctx.paths.transcripts, record_id=problem_id, run_id=ctx.run_id, model=a.model,
        effort=a.effort, system=system_prompt(ctx.profile),
        user=render_input(problem, ctx.optional(ctx.investigations, problem_id), ctx.optional(ctx.assessments, problem_id)),
        schema=FIT_SCHEMA, tools=[], max_budget_usd=a.max_budget_usd)
    try:
        out = FitOutput.model_validate(res.structured_output)
    except ValidationError as e:
        raise AgentError(f"schema: {e.errors()[:3]}", res.transcript) from e
    result = apply(out, ctx.profile, self_rating_files=ctx.cfg.self_rating_files,
                   self_rating_cap=ctx.cfg.self_rating_cap, no_advantage_cap=ctx.cfg.no_advantage_cap)
    record = {"problem_id": problem_id, "revision": 1, "problem_revision": problem["revision"],
              "profile_digest": ctx.profile.digest, **result,
              "run": run_info(res, model=a.model, effort=a.effort, transcript=transcript), "history": []}
    record = with_history(ctx.fits, problem_id, record, keep=("revision", "personal_advantage", "profile_digest", "run"))
    ctx.fits.save(record, problem_id)
    return record


def assess(ctx: PFContext, problem_ids: list[str]) -> dict[str, str]:
    """Fit per problem; returns {problem_id: error}. Every id is checked before any spend."""
    for pid in problem_ids:
        if (refused := refusal(ctx.problems, pid)) is not None:
            raise refused

    def one(pid: str) -> str:
        rec = assess_one(ctx, pid)
        return f"advantage {rec['personal_advantage']['score']}/10, {len(rec['advantages'])} advantages, {len(rec['warnings'])} warnings"
    return run_each(problem_ids, one, log=log, tag="fit", budget=ctx.cfg.agent.max_budget_usd)
