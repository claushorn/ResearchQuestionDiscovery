"""Opportunity per problem: one agent session over everything the earlier stages found, then code-side rules,
the recommendation and the brief. A personal fit is required; novelty and economic value are optional."""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from opportunitygenerator.brief import render
from opportunitygenerator.config import OGConfig, OGPaths
from opportunitygenerator.ids import opp_id_for
from opportunitygenerator.prompt import SYSTEM, render_input
from opportunitygenerator.rules import check, recommend
from opportunitygenerator.schema import OG_SCHEMA, OGOutput
from rqd.claude_code import ClaudeCodeClient
from rqd.errors import AgentError, ConfigError, RqdError
from rqd.http import Fetcher
from rqd.investigation import run_agent_logged, run_each, run_info, search_summary, with_history
from rqd.numbers import unsupported_amounts, unsupported_numbers
from rqd.records import YamlStore
from rqd.timeutil import utcnow
from rqd.verify import verify_work

log = logging.getLogger("opportunitygenerator")
TOOLS = ["WebSearch", "WebFetch"]
TEXTS = ("title_question", "novelty_reasoning", "value_reasoning", "tractability_reasoning", "upside_reasoning",
         "why_unsolved", "current_best_approach", "what_we_could_test", "first_experiment", "if_successful",
         "if_failed", "thesis", "next_step_reason")


@dataclass
class OGStores:
    """The stores this stage reads (earlier stages, read-only) and writes (opportunities); no agent client."""
    problems: YamlStore
    fits: YamlStore
    investigations: YamlStore
    assessments: YamlStore
    opportunities: YamlStore

    @classmethod
    def open(cls, paths: OGPaths, cfg: OGConfig) -> "OGStores":
        def store(root: str, sub: str, required: bool = False) -> YamlStore:
            d = (paths.root / root).resolve() / sub
            if required and not d.is_dir():
                raise ConfigError(f"directory not found: {d}", fix="Set the *_root paths in OpportunityGenerator/config.yaml")
            return YamlStore(d)
        return cls(store(cfg.problemextractor_root, "problems", True), store(cfg.personalfit_root, "fits"),
                   store(cfg.noveltyinvestigator_root, "investigations"), store(cfg.economicvalue_root, "assessments"),
                   YamlStore(paths.opportunities))

    def optional(self, store: YamlStore, problem_id: str) -> dict | None:
        return store.load(problem_id) if store.exists(problem_id) else None


@dataclass
class OGContext:
    cfg: OGConfig
    paths: OGPaths
    stores: OGStores
    client: ClaudeCodeClient
    fetcher: Fetcher
    run_id: str

    @classmethod
    def open(cls, paths: OGPaths, cfg: OGConfig, client: ClaudeCodeClient, fetcher: Fetcher,
             run_id: str | None = None) -> "OGContext":
        return cls(cfg, paths, OGStores.open(paths, cfg), client, fetcher, run_id or utcnow().strftime("%Y%m%dT%H%M%SZ"))


NOVELTY_STATUSES = ("likely_open", "partially_solved", "solved", "unclear")


def load_inputs(stores: OGStores, pid: str) -> tuple[dict, dict, dict | None, dict | None]:
    """Problem, fit, novelty, EV — each checked for the keys this stage reads, before any spend."""
    if not stores.problems.exists(pid):
        raise RqdError(f"no problem {pid}", fix="See `uv run problemextractor list`")
    if not stores.fits.exists(pid):
        raise RqdError(f"no fit for {pid}", fix=f"Run `uv run fit assess {pid}` first")
    problem, fit = stores.problems.load(pid), stores.fits.load(pid)
    novelty, ev = stores.optional(stores.investigations, pid), stores.optional(stores.assessments, pid)
    checks = [("problem", problem, lambda r: (r["revision"], r["problem"]["precise_statement"]),
               f"Re-run `problemextractor` for {pid}"),
              ("fit", fit, lambda r: (r["revision"], r["problem_revision"], r["profile_digest"], r["advantages"],
                                      r["personal_advantage"]["score"], r["personal_advantage"]["confidence"]),
               f"Re-run `uv run fit assess {pid}`"),
              ("novelty investigation", novelty, lambda r: (r["revision"], r["confidence"], r["novelty"]["status"]),
               f"Re-run `noveltyinvestigator investigate {pid}` or remove the file"),
              ("economic value assessment", ev, lambda r: (r["revision"], r["confidence"], r["economic_value"]["buyer"],
                                                          r["economic_value"]["beneficiary"]["type"],
                                                          r["economic_value"]["potential_value"]),
               f"Re-run `economicvalue assess {pid}` or remove the file")]
    for name, record, read, fix in checks:
        if record is None:
            continue
        try:
            read(record)
        except (KeyError, TypeError) as e:
            raise RqdError(f"malformed {name} record for {pid} (missing {e!s})", fix=fix) from e
    if novelty and novelty["novelty"]["status"] not in NOVELTY_STATUSES:
        raise RqdError(f"unknown novelty status {novelty['novelty']['status']!r} for {pid}",
                       fix=f"Re-run `noveltyinvestigator investigate {pid}` (statuses: {', '.join(NOVELTY_STATUSES)})")
    if fit["problem_revision"] != problem["revision"]:
        raise RqdError(f"the fit for {pid} is stale (problem revision {fit['problem_revision']} -> {problem['revision']})",
                       fix=f"Run `uv run fit assess {pid}` first")
    return problem, fit, novelty, ev


def _inputs(problem: dict, fit: dict, novelty: dict | None, ev: dict | None) -> dict:
    return {"problem_revision": problem["revision"], "fit_revision": fit["revision"],
            "fit_profile_digest": fit["profile_digest"], "novelty_revision": novelty["revision"] if novelty else None,
            "ev_revision": ev["revision"] if ev else None}


def stale_inputs(stores: OGStores, record: dict) -> list[str]:
    """Which inputs changed since the opportunity was generated."""
    pid = record["problem_id"]
    if not stores.problems.exists(pid) or not stores.fits.exists(pid):
        return ["problem or fit removed"]
    now = _inputs(stores.problems.load(pid), stores.fits.load(pid), stores.optional(stores.investigations, pid),
                  stores.optional(stores.assessments, pid))
    was = record["inputs"]
    names = {"problem_revision": "problem", "fit_revision": "fit", "fit_profile_digest": "fit",
             "novelty_revision": "novelty", "ev_revision": "economic value"}
    return sorted({names[k] for k in names if now[k] != was[k]})


def _backing(problem: dict, novelty: dict | None, ev: dict | None, evidence: list[dict]) -> tuple[list[str], list[float]]:
    """Texts that may state numbers (verified quotes and the earlier stages' records), and values backed there."""
    # only verified quotes and the problem's stated (not *_inferred) fields: model prose never backs a number
    quotes = [e["quote"] for e in evidence if e["verification"] == "verified"]
    quotes += [problem["problem"]["precise_statement"], (problem.get("current_state") or {}).get("known_solution", ""),
               (problem.get("failure") or {}).get("what_current_methods_cannot_do", "")]
    if novelty:
        quotes += [w["quote"] for w in novelty.get("closest_work", []) if w.get("verification") == "verified"]
    backed = []
    if ev:
        quotes += [e["quote"] for e in ev.get("evidence", []) if e.get("verification") == "verified"]
        pv = ev["economic_value"]["potential_value"]
        if pv != "unknown":
            backed += [pv["low"], pv["high"]]
    return quotes, backed


def generate_one(ctx: OGContext, problem_id: str) -> dict:
    a = ctx.cfg.agent
    problem, fit, novelty, ev = load_inputs(ctx.stores, problem_id)
    res, transcript = run_agent_logged(
        ctx.client, transcripts_dir=ctx.paths.transcripts, record_id=problem_id, run_id=ctx.run_id, model=a.model,
        effort=a.effort, system=SYSTEM.format(min_searches=a.min_searches), user=render_input(problem, fit, novelty, ev),
        schema=OG_SCHEMA, tools=TOOLS, max_budget_usd=a.max_budget_usd)
    try:
        out = OGOutput.model_validate(res.structured_output)
        check(out, novelty, ev)
    except (ValidationError, ValueError) as e:
        raise AgentError(f"rejected output: {e}", res.transcript) from e
    evidence = [e.model_dump() | {"verification": verify_work(ctx.fetcher, e.url, e.quote)} for e in out.evidence]
    profile = {"novelty": out.novelty_score, "economic_value": out.economic_value_score,
               "tractability": out.tractability_score, "personal_advantage": fit["personal_advantage"]["score"],
               "asymmetric_upside": out.asymmetric_upside,
               "likely_engagement": {k: getattr(out, f"engagement_{k}") for k in ("consulting", "research", "startup", "employment")}}
    status = novelty["novelty"]["status"] if novelty else None
    recommendation, reason = recommend(profile, status, out.next_step, out.next_step_reason, ctx.cfg.thresholds)
    quotes, backed = _backing(problem, novelty, ev, evidence)
    opp_id = opp_id_for(ctx.stores.opportunities, problem_id)
    record = {
        "id": opp_id, "problem_id": problem_id, "revision": 1, "title": out.title_question,
        "opportunity_profile": profile,
        "reasoning": {"novelty": out.novelty_reasoning, "economic_value": out.value_reasoning,
                      "tractability": out.tractability_reasoning, "asymmetric_upside": out.upside_reasoning},
        "confidence": {"novelty": novelty["confidence"] if novelty else None, "value": ev["confidence"] if ev else None,
                       "tractability": out.tractability_confidence, "fit": fit["personal_advantage"]["confidence"]},
        "thesis": out.thesis, "recommendation": recommendation, "recommendation_reason": reason,
        "brief_sections": {k: getattr(out, k) for k in ("why_unsolved", "current_best_approach", "what_we_could_test",
                                                        "first_experiment", "first_experiment_hours",
                                                        "first_experiment_compute_usd", "if_successful", "if_failed")},
        "inputs": _inputs(problem, fit, novelty, ev),
        "evidence": evidence,
        "warnings": {"unverified_evidence": [e["url"] for e in evidence if e["verification"] != "verified"],
                     "unsupported_numbers": unsupported_numbers([(k, getattr(out, k)) for k in TEXTS], quotes, backed),
                     "unsupported_amounts": unsupported_amounts([(k, getattr(out, k)) for k in TEXTS], quotes, backed)},
        "search": search_summary(res.tool_calls, a.min_searches),
        "run": run_info(res, model=a.model, effort=a.effort, transcript=transcript), "history": []}
    record = with_history(ctx.stores.opportunities, opp_id, record,
                          keep=("revision", "opportunity_profile", "recommendation", "inputs", "run"))
    ctx.stores.opportunities.save(record, opp_id)
    ctx.paths.briefs.mkdir(parents=True, exist_ok=True)
    (ctx.paths.briefs / f"{opp_id}.md").write_text(render(record, problem, fit, novelty, ev, ctx.cfg.profile_name),
                                                   encoding="utf-8")
    return record


def generate(ctx: OGContext, problem_ids: list[str]) -> dict[str, str]:
    """Returns {problem_id: error}. Every input and the opportunity store are checked before any spend."""
    for pid in problem_ids:
        load_inputs(ctx.stores, pid)
        opp_id_for(ctx.stores.opportunities, pid)

    def one(pid: str) -> str:
        rec = generate_one(ctx, pid)
        return f"{rec['id']} {rec['recommendation']}"
    return run_each(problem_ids, one, log=log, tag="opportunity", budget=ctx.cfg.agent.max_budget_usd)
