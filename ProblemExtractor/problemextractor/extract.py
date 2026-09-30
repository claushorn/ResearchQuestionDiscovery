"""Turn new SourceScout candidates into precise, merged problem records (one `claude -p`/API call per candidate)."""
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic
import yaml

from problemextractor.config import PEConfig, PEPaths
from problemextractor.records import merge_into, new_record, problem_id_for
from rqd.records import YamlStore
from problemextractor.schema import PE_SCHEMA, PEOutput
from problemextractor.similarity import shortlist
from problemextractor.state import PEState
from rqd.claude_code import parse_structured, raise_if_not_transient
from rqd.errors import ConfigError, ItemExtractionError
from rqd.quotes import quote_in_text
from rqd.timeutil import iso, utcnow
from sourcescout.store import Store

log = logging.getLogger("problemextractor")

SYSTEM_PROMPT = """You turn one candidate problem from a source document into a precise problem record, and decide whether it is the same problem as one already on file.

Document fields come only from the source document. Your own expertise goes only into the two *_inferred fields. Do not judge novelty, value or feasibility.

Document fields (each at most 60 words, plain technical language):
- precise_statement: the problem, precise enough that someone could tell whether a result solves it.
- known_solution: what the document says is currently done or available; "not stated" if it does not say.
- what_current_methods_cannot_do: what the document says current methods fail at; "not stated" if it does not say.
- desired_capability: what a solution must be able to do, as the document describes it.
- why_it_matters: why the document says it matters (who needs it, stated scale, cost or funding).
- unsolved_explicit: true only if the document itself says the problem is open, unsolved, a limitation or being sought; then explicit_evidence is a verbatim quote of at most 50 words, copied character for character, no ellipses.
- unsolved_inferred: true if you consider it unsolved without an explicit statement in the document.

Your expert knowledge (each at most 80 words; empty string if you are not confident; state it as your assessment of the current state of the art, not as a fact from the document):
- known_solution_inferred: the methods, tools or results you know are currently used for this problem.
- what_current_methods_cannot_do_inferred: what, to your knowledge, those methods still cannot do.

Merging: the message lists existing problems as [id] statement. Set merge_with to one of those ids only if it is the same problem (the same desired capability and the same failure), not merely the same field. Otherwise null. merge_reason: one sentence."""


@dataclass
class PERunReport:
    run_id: str
    started: str
    processed: int = 0
    new: int = 0
    merged: int = 0
    unverified: int = 0
    retries: int = 0  # claude -p structured-output rewrites (num_turns > 2); 0 on the api backend
    output_tokens: int = 0
    input_tokens: int = 0
    invalid_merges: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def tokens_per_candidate(self) -> float | None:
        return self.output_tokens / self.processed if self.processed else None

    def save(self, runs_dir: Path) -> Path:
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{self.run_id}.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path

    def render(self, budget: int) -> str:
        tpc = self.tokens_per_candidate()
        lines = [f"Run {self.run_id} (started {self.started})",
                 f"candidates processed: {self.processed}  new problems: {self.new}  merged: {self.merged}  "
                 f"unverified explicit quotes: {self.unverified}  structured-output retries: {self.retries}",
                 f"output tokens: {self.output_tokens}  per candidate: {f'{tpc:.0f}' if tpc is not None else 'n/a'}"
                 + (f"  BUDGET VIOLATION (> {budget})" if tpc is not None and tpc > budget else f"  (limit {budget})")]
        for title, entries in [("INVALID MERGE IDS (treated as new)", self.invalid_merges), ("FAILURES", self.failures)]:
            lines += ["", f"{title}: {len(entries)}"] + [f"  {x}" for x in entries]
        return "\n".join(lines)


@dataclass
class PEContext:
    cfg: PEConfig
    paths: PEPaths
    problems: YamlStore
    state: PEState
    ss_root: Path
    ss_store: Store
    report: PERunReport
    docs: dict[str, str]  # problem_id -> text used for the similarity shortlist (kept in memory during a run)

    @classmethod
    def open(cls, paths: PEPaths, cfg: PEConfig, run_id: str | None = None) -> "PEContext":
        ss_root = (paths.root / cfg.sourcescout_root).resolve()
        db = ss_root / "data" / "scout.db"
        if not db.exists():
            raise ConfigError(f"SourceScout store not found at {db}",
                              fix="Set sourcescout_root in ProblemExtractor/config.yaml, or run `sourcescout run` first")
        now = utcnow()
        problems = YamlStore(paths.problems)
        docs = {r["problem_id"]: _doc(r) for r in problems.all()}
        return cls(cfg, paths, problems, PEState(paths.db), ss_root, Store(db),
                   PERunReport(run_id or now.strftime("%Y%m%dT%H%M%SZ"), iso(now)), docs)


def _doc(record: dict) -> str:
    return f"{record['problem']['precise_statement']} {record['desired_capability']}"


def new_candidates(ctx: PEContext) -> list[dict]:
    """Unprocessed SourceScout candidates, tier A first, oldest first within a tier."""
    out = []
    for path in sorted((ctx.ss_root / "output").glob("*/*.yaml")):
        c = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not ctx.state.is_processed(c["candidate_id"]):
            out.append(c)
    return sorted(out, key=lambda c: (c["source"]["tier"], c["extracted_with"]["at"], c["candidate_id"]))


def render(candidate: dict, item_text: str, shortlisted: list[str], docs: dict[str, str]) -> str:
    s = candidate["source"]
    existing = "\n".join(f"[{pid}] {docs[pid]}" for pid in shortlisted) or "(none)"
    return (f"<candidate source=\"{candidate['source_id']}\" tier=\"{s['tier']}\">\n<title>{s['title']}</title>\n"
            f"<url>{s['url']}</url>\n<statement>{candidate['candidate_problem']['statement']}</statement>\n"
            f"<payment_signal>{json.dumps(candidate['payment_signal'])}</payment_signal>\n</candidate>\n"
            f"<document>\n{item_text}\n</document>\n<existing_problems>\n{existing}\n</existing_problems>")


def build_params(ctx: PEContext, candidate: dict, item_text: str, shortlisted: list[str]) -> dict:
    cfg = ctx.cfg.extraction
    return {"model": cfg.model, "max_tokens": cfg.max_tokens,
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "output_config": {"effort": cfg.effort, "format": {"type": "json_schema", "schema": PE_SCHEMA}},
            "messages": [{"role": "user", "content": render(candidate, item_text, shortlisted, ctx.docs)}]}


def process(ctx: PEContext, client, candidate: dict) -> None:
    cid = candidate["candidate_id"]
    item = ctx.ss_store.get(candidate["item_id"])
    if item is None:
        raise ItemExtractionError(f"source item {candidate['item_id']} is not in the SourceScout store")
    shortlisted = shortlist(candidate["candidate_problem"]["statement"], ctx.docs, ctx.cfg.extraction.shortlist_size)
    try:
        message = client.messages.create(**build_params(ctx, candidate, item.text, shortlisted))
    except anthropic.APIError as e:
        raise_if_not_transient(e)
        raise ItemExtractionError(f"api: {e}") from e
    ctx.report.output_tokens += message.usage.output_tokens
    ctx.report.input_tokens += message.usage.input_tokens
    ctx.report.retries += max(0, getattr(message, "num_turns", 0) - 2)
    out: PEOutput = parse_structured(message, PEOutput)
    now = iso(utcnow())
    extracted_with = {"model": ctx.cfg.extraction.model, "run_id": ctx.report.run_id,
                      "output_tokens": message.usage.output_tokens, "at": now}
    if out.merge_with is not None and out.merge_with not in shortlisted:
        ctx.report.invalid_merges.append(f"{cid}: {out.merge_with}")
        out = out.model_copy(update={"merge_with": None})
    if out.merge_with is not None:
        record = merge_into(ctx.problems.load(out.merge_with), candidate, out, extracted_with)
        ctx.problems.save(record, record["problem_id"])
        ctx.state.record(cid, out.merge_with, "merged", now)
        ctx.report.merged += 1
        return
    verified = quote_in_text(out.explicit_evidence, item.text) if out.unsolved_explicit else None
    ctx.report.unverified += verified is False
    pid = problem_id_for(cid)
    record = new_record(pid, candidate, out, verified, extracted_with)
    ctx.problems.save(record, record["problem_id"])
    ctx.docs[pid] = _doc(record)
    ctx.state.record(cid, pid, "new", now)
    ctx.report.new += 1


def run_extraction(ctx: PEContext, client, limit: int | None = None) -> None:
    candidates = new_candidates(ctx)[:limit] if limit is not None else new_candidates(ctx)
    log.info("processing %d new candidates (%d problems on file)", len(candidates), len(ctx.docs))
    for i, c in enumerate(candidates, 1):
        started = time.monotonic()
        before = (ctx.report.new, ctx.report.merged)
        try:
            process(ctx, client, c)
        except ItemExtractionError as e:
            ctx.report.failures.append(f"{c['candidate_id']}: {e}")
            log.warning("[pe %d/%d] %s -> FAILED %s", i, len(candidates), c["candidate_id"], str(e)[:200])
            continue
        ctx.report.processed += 1
        outcome = "new problem" if ctx.report.new > before[0] else "merged"
        log.info("[pe %d/%d] %s (%s) -> %s (%.1fs)", i, len(candidates), c["candidate_id"], c["source_id"],
                 outcome, time.monotonic() - started)
