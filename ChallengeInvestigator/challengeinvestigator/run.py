"""Headroom gate (all finished challenges; scraped leaderboard, an agent only to look up a missing baseline) and
investigation (picked; agent session) with code-side checks."""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from challengeinvestigator.config import CIConfig, CIPaths
from challengeinvestigator.headroom import from_leaderboard, needs_baseline
from challengeinvestigator.leaderboard import LeaderboardError, NoLeaderboard, fetch_leaderboard
from challengeinvestigator.prompt import BASELINE_PROMPT, INVESTIGATE_PROMPT, render_challenge
from challengeinvestigator.schema import BASELINE_SCHEMA, INVESTIGATE_SCHEMA, BaselineOutput, InvestigateOutput
from rqd.claude_code import ClaudeCodeClient
from rqd.config import AgentCfg
from rqd.errors import AgentError, ConfigError, RqdError
from rqd.http import Fetcher
from rqd.investigation import run_agent_logged, run_each, run_info, search_summary, with_history
from rqd.numbers import same_number, stated, unsupported_numbers
from rqd.records import YamlStore
from rqd.timeutil import utcnow
from rqd.verify import verify_work
from sourcescout.store import Store, StoredItem

log = logging.getLogger("challengeinvestigator")
TOOLS = ["WebSearch", "WebFetch"]


@dataclass
class CIContext:
    cfg: CIConfig
    paths: CIPaths
    store: Store               # SourceScout's store (read-only use)
    challenges: YamlStore
    client: ClaudeCodeClient
    fetcher: Fetcher
    run_id: str

    @classmethod
    def open(cls, paths: CIPaths, cfg: CIConfig, client: ClaudeCodeClient, fetcher: Fetcher,
             run_id: str | None = None) -> "CIContext":
        db = (paths.root / cfg.sourcescout_root).resolve() / "data" / "scout.db"
        if not db.exists():
            raise ConfigError(f"SourceScout store not found at {db}", fix="Set sourcescout_root in ChallengeInvestigator/config.yaml")
        return cls(cfg, paths, Store(db), YamlStore(paths.challenges), client, fetcher,
                   run_id or utcnow().strftime("%Y%m%dT%H%M%SZ"))


def _not_finished(item_id: str) -> RqdError:
    return RqdError(f"{item_id} is not a finished challenge in the SourceScout store",
                    fix="See `uv run challenges list` (finished challenges come from `sourcescout scan`)")


def _finished(ctx: CIContext, item_id: str) -> StoredItem:
    item = ctx.store.get(item_id)
    if item is None or not item.finished:
        raise _not_finished(item_id)
    return item


def refusal(store: Store, challenges: YamlStore, item_id: str, force: bool) -> RqdError | None:
    """Pre-spend check of `investigate` on the stores alone: None = runnable, else the refusal (message and fix)."""
    item = store.get(item_id)
    if item is None or not item.finished:
        return _not_finished(item_id)
    if not force and challenges.exists(item_id) and challenges.load(item_id)["headroom"]["verdict"] == "solved":
        return RqdError(f"{item_id}: the headroom check found it solved", fix="Pick another challenge, or pass --force")
    return None


def _session(ctx: CIContext, record_id: str, agent: AgentCfg, prompt: str, user: str, schema: dict, model_cls):
    res, transcript = run_agent_logged(ctx.client, transcripts_dir=ctx.paths.transcripts, record_id=record_id,
                                       run_id=ctx.run_id, model=agent.model, effort=agent.effort,
                                       system=prompt.format(min_searches=agent.min_searches), user=user,
                                       schema=schema, tools=TOOLS, max_budget_usd=agent.max_budget_usd)
    try:
        out = model_cls.model_validate(res.structured_output)
    except ValidationError as e:
        raise AgentError(f"schema: {e.errors()[:3]}", res.transcript) from e
    verification = [verify_work(ctx.fetcher, e.url, e.quote) for e in out.evidence]
    meta = {"search": search_summary(res.tool_calls, agent.min_searches),
            "run": run_info(res, model=agent.model, effort=agent.effort, transcript=transcript)}
    return out, verification, meta


def _lookup_baseline(ctx: CIContext, item: StoredItem, h: dict) -> tuple[dict | None, dict]:
    """A missing baseline from an agent session; kept only if a verified quote states it."""
    out, verification, meta = _session(ctx, f"{item.item_id}-baseline", ctx.cfg.baseline_agent, BASELINE_PROMPT,
                                       render_challenge(item, h), BASELINE_SCHEMA, BaselineOutput)
    lookup = {"evidence": [e.model_dump() | {"verification": v} for e, v in zip(out.evidence, verification)],
              "reasoning": out.reasoning, **meta, "warnings": []}
    i = out.evidence_index
    if out.baseline is None:
        lookup["warnings"].append("no baseline found")
    elif not 1 <= i <= len(out.evidence) or verification[i - 1] != "verified":
        lookup["warnings"].append(f"baseline {out.baseline:g}: evidence {i} is not a verified quote")
    elif not stated(out.baseline, out.evidence[i - 1].quote):
        lookup["warnings"].append(f"baseline {out.baseline:g} not in evidence {i}'s quote")
    else:
        ev = out.evidence[i - 1]
        return {"value": out.baseline, "basis": {"type": "source", "url": ev.url, "quote": ev.quote,
                                                 "verification": "verified"}}, lookup
    return None, lookup


def _not_applicable(reason: str) -> dict:
    return {"metric": None, "direction": None, "leaderboard": None, "winner": None, "ceiling": None, "baseline": None,
            "normalized_headroom": None, "verdict": "not_applicable", "warnings": [reason]}


def headroom_one(ctx: CIContext, item_id: str) -> dict:
    item = _finished(ctx, item_id)
    kind = ctx.cfg.leaderboard_sources.get(item.source_id)
    if kind is None:
        h = _not_applicable(f"no leaderboard scraper for source {item.source_id}")
    else:
        try:
            lb = fetch_leaderboard(ctx.fetcher, kind, item.url)
        except NoLeaderboard as e:
            h = _not_applicable(str(e))
        else:
            h = from_leaderboard(lb, ctx.cfg.metric_bounds, ctx.cfg.headroom_threshold)
            lookup = None
            if needs_baseline(h):
                baseline, lookup = _lookup_baseline(ctx, item, h)
                if baseline is not None:
                    h = from_leaderboard(lb, ctx.cfg.metric_bounds, ctx.cfg.headroom_threshold, baseline)
                h["warnings"] += lookup["warnings"]
            h["baseline_lookup"] = lookup
    h["threshold"] = ctx.cfg.headroom_threshold
    h["checked_at"] = utcnow().isoformat(timespec="seconds")
    old = ctx.challenges.load(item_id) if ctx.challenges.exists(item_id) else {}
    record = {"item_id": item_id, "revision": 1,
              "challenge": {"title": item.title, "url": item.url, "source_id": item.source_id},
              "headroom": h, "investigation": old.get("investigation"), "history": []}
    record = with_history(ctx.challenges, item_id, record, keep=("revision", "headroom", "investigation"))
    ctx.challenges.save(record, item_id)
    return record


def _headline(h: dict) -> str:
    if h["normalized_headroom"] is None:
        return h["verdict"]
    return f"{h['verdict']} {h['normalized_headroom'] * 100:.0f}%"


def check_headroom(ctx: CIContext, item_ids: list[str] | None = None) -> dict[str, str]:
    """Headroom for the given finished challenges, or every finished challenge not checked yet."""
    if item_ids:
        for i in item_ids:
            _finished(ctx, i)
    else:
        item_ids = [i.item_id for i in ctx.store.finished_items() if not ctx.challenges.exists(i.item_id)]
    return run_each(item_ids, lambda i: _headline(headroom_one(ctx, i)["headroom"]), log=log, tag="headroom",
                    budget=ctx.cfg.baseline_agent.max_budget_usd, item_errors=(AgentError, LeaderboardError))


def investigate_one(ctx: CIContext, item_id: str, force: bool) -> str:
    item = _finished(ctx, item_id)
    if not ctx.challenges.exists(item_id):
        headroom_one(ctx, item_id)
    record = ctx.challenges.load(item_id)
    if record["headroom"]["verdict"] == "solved" and not force:
        return "skipped: the headroom check found it solved (use --force)"
    out, verification, meta = _session(ctx, f"{item_id}-investigate", ctx.cfg.investigate_agent, INVESTIGATE_PROMPT,
                                       render_challenge(item, record["headroom"]), INVESTIGATE_SCHEMA, InvestigateOutput)
    warnings = {"dropped_solutions": [], "dropped_scores": [], "unsupported_numbers": []}
    h = record["headroom"]
    top = (h.get("leaderboard") or {}).get("top", [])
    solutions = []
    for s in out.solutions:
        if not (1 <= s.evidence <= len(out.evidence) and verification[s.evidence - 1] == "verified"):
            warnings["dropped_solutions"].append(f"{s.team} ({s.title}): evidence {s.evidence} not verified")
            continue
        entry = s.model_dump()
        if s.score is not None and not stated(s.score, out.evidence[s.evidence - 1].quote) \
                and not any(same_number(s.score, r["score"]) and r["team"].casefold() == s.team.casefold() for r in top):
            warnings["dropped_scores"].append(f"{s.team}: {s.score:g} not in evidence {s.evidence}'s quote")
            entry["score"] = None
        solutions.append(entry)
    quotes = [e.quote for e, v in zip(out.evidence, verification) if v == "verified"]
    backed = [h[k]["value"] for k in ("winner", "ceiling", "baseline") if h[k]] + [r["score"] for r in top] \
        + [b["score"] for b in (h.get("leaderboard") or {}).get("baselines", [])]
    texts = [("summary", out.summary)] + [(f"solutions[{i}].approach", s.approach) for i, s in enumerate(out.solutions, 1)]
    for i, idea in enumerate(out.ideas, 1):
        texts += [(f"ideas[{i}].{f}", getattr(idea, f)) for f in ("idea", "builds_on", "why_it_could_win", "risks")]
    warnings["unsupported_numbers"] = unsupported_numbers(texts, quotes, backed)
    record["investigation"] = {
        "solutions": solutions, "ideas": [i.model_dump() for i in out.ideas], "summary": out.summary,
        "evidence": [e.model_dump() | {"verification": v} for e, v in zip(out.evidence, verification)],
        "warnings": warnings, **meta, "forced": record["headroom"]["verdict"] == "solved"}
    ctx.challenges.save(record, item_id)
    return f"{len(solutions)} solutions, {len(out.ideas)} ideas, {sum(len(v) for v in warnings.values())} warnings"


def investigate(ctx: CIContext, item_ids: list[str], force: bool = False) -> dict[str, str]:
    """Checks every id before any spend: known-solved challenges are refused unless forced."""
    for i in item_ids:
        if (refused := refusal(ctx.store, ctx.challenges, i, force)) is not None:
            raise refused
    return run_each(item_ids, lambda i: investigate_one(ctx, i, force), log=log, tag="investigate",
                    budget=ctx.cfg.investigate_agent.max_budget_usd)
