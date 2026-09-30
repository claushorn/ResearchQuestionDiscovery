"""Headroom gate (all finished challenges) and investigation (picked) as agent sessions with code-side checks."""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from challengeinvestigator.config import CIConfig, CIPaths
from challengeinvestigator.headroom import VERIFIED, _stated, compute
from challengeinvestigator.prompt import HEADROOM_PROMPT, INVESTIGATE_PROMPT, render_challenge
from challengeinvestigator.schema import HEADROOM_SCHEMA, INVESTIGATE_SCHEMA, HeadroomOutput, InvestigateOutput
from rqd.claude_code import ClaudeCodeClient
from rqd.config import AgentCfg
from rqd.errors import AgentError, ConfigError, RqdError
from rqd.http import Fetcher
from rqd.investigation import run_agent_logged, run_each, run_info, search_summary, with_history
from rqd.numbers import figure_in_quote, numbers_in_text
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


def _finished(ctx: CIContext, item_id: str) -> StoredItem:
    item = ctx.store.get(item_id)
    if item is None or not item.finished:
        raise RqdError(f"{item_id} is not a finished challenge in the SourceScout store",
                       fix="See `uv run challenges list` (finished challenges come from `sourcescout scan`)")
    return item


def _session(ctx: CIContext, record_id: str, agent: AgentCfg, prompt: str, user: str, schema: dict, model_cls):
    res, transcript = run_agent_logged(ctx.client, transcripts_dir=ctx.paths.transcripts, record_id=record_id,
                                       run_id=ctx.run_id, model=agent.model, effort=agent.effort,
                                       system=prompt.format(min_searches=agent.min_searches), user=user,
                                       schema=schema, tools=TOOLS, max_budget_usd=agent.max_budget_usd)
    try:
        out = model_cls.model_validate(res.structured_output)
    except ValidationError as e:
        raise AgentError(f"schema: {e.errors()[:3]}", res.transcript) from e
    # table rows (leaderboards, result tables in papers) verify structurally: numbers share one <tr> with a quote word
    verification = [verify_work(ctx.fetcher, e.url, e.quote, table=True) for e in out.evidence]
    meta = {"search": search_summary(res.tool_calls, agent.min_searches),
            "run": run_info(res, model=agent.model, effort=agent.effort, transcript=transcript)}
    return out, verification, meta


def headroom_one(ctx: CIContext, item_id: str) -> dict:
    item = _finished(ctx, item_id)
    out, verification, meta = _session(ctx, f"{item_id}-headroom", ctx.cfg.headroom_agent, HEADROOM_PROMPT,
                                       render_challenge(item), HEADROOM_SCHEMA, HeadroomOutput)
    h = compute(out, verification, ctx.cfg.headroom_threshold)
    h["evidence"] = [e.model_dump() | {"verification": v} for e, v in zip(out.evidence, verification)]
    h.update(meta)
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
                    budget=ctx.cfg.headroom_agent.max_budget_usd)


def _supported_number(value: float, pct: bool, quotes: list[str]) -> bool:
    if pct:
        return any(figure_in_quote(value / 100, q, "%") for q in quotes)
    return any(_stated(value, q) for q in quotes)


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
    solutions = []
    for s in out.solutions:
        if not (1 <= s.evidence <= len(out.evidence) and verification[s.evidence - 1] in VERIFIED):
            warnings["dropped_solutions"].append(f"{s.team} ({s.title}): evidence {s.evidence} not verified")
            continue
        entry = s.model_dump()
        if s.score is not None and not _stated(s.score, out.evidence[s.evidence - 1].quote):
            warnings["dropped_scores"].append(f"{s.team}: {s.score:g} not in evidence {s.evidence}'s quote")
            entry["score"] = None
        solutions.append(entry)
    quotes = [e.quote for e, v in zip(out.evidence, verification) if v in VERIFIED]
    texts = [("summary", out.summary)] + [(f"solutions[{i}].approach", s.approach) for i, s in enumerate(out.solutions, 1)]
    for i, idea in enumerate(out.ideas, 1):
        texts += [(f"ideas[{i}].{f}", getattr(idea, f)) for f in ("idea", "builds_on", "why_it_could_win", "risks")]
    for name, text in texts:
        for value, pct in numbers_in_text(text):
            if not _supported_number(value, pct, quotes):
                warnings["unsupported_numbers"].append(f"{name}: {value:g}{'%' if pct else ''}")
    record["investigation"] = {
        "solutions": solutions, "ideas": [i.model_dump() for i in out.ideas], "summary": out.summary,
        "evidence": [e.model_dump() | {"verification": v} for e, v in zip(out.evidence, verification)],
        "warnings": warnings, **meta, "forced": record["headroom"]["verdict"] == "solved"}
    ctx.challenges.save(record, item_id)
    return f"{len(solutions)} solutions, {len(out.ideas)} ideas, {sum(len(v) for v in warnings.values())} warnings"


def investigate(ctx: CIContext, item_ids: list[str], force: bool = False) -> dict[str, str]:
    """Checks every id before any spend: known-solved challenges are refused unless forced."""
    for i in item_ids:
        _finished(ctx, i)
        if not force and ctx.challenges.exists(i) and ctx.challenges.load(i)["headroom"]["verdict"] == "solved":
            raise RqdError(f"{i}: the headroom check found it solved", fix="Pick another challenge, or pass --force")
    return run_each(item_ids, lambda i: investigate_one(ctx, i, force), log=log, tag="investigate",
                    budget=ctx.cfg.investigate_agent.max_budget_usd)
