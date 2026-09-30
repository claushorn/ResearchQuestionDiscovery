import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import anthropic
import yaml
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from sourcescout.categories import Category
from sourcescout.config import ExtractionCfg
from rqd.claude_code import ClaudeCodeClient, parse_structured, raise_if_not_transient
from rqd.errors import ExtractionConfigError, ItemExtractionError
from rqd.quotes import quote_in_text
from rqd.records import YamlStore
from sourcescout.registry import Registry, Source
from sourcescout.report import RunReport
from sourcescout.schema import EXTRACTION_SCHEMA, ExtractionResult, length_violations
from sourcescout.store import Store, StoredItem
from rqd.timeutil import iso, utcnow

log = logging.getLogger("sourcescout")
MAX_LINKS = 50  # links shown to the model, numbered from 1

SYSTEM_PROMPT = """You extract candidate technical problems from one source document for a problem-discovery pipeline.

A candidate is a concrete technical problem (engineering, machine learning, data science, optimisation, computational biology, or similar) that the document states is unsolved, not solved well enough, or that the publishing organisation is seeking or funding a solution for.

Extract; do not analyse. Report only what the document states. Do not estimate value, feasibility, market size or difficulty, and do not add knowledge from outside the document.

Rules:
- Return at most 3 candidates. Return an empty list when the document states no such problem, for example a sales, legal or generic operations job ad, a product announcement, or a write-up of a solved problem.
- statement: the problem in at most 60 words, in plain technical language.
- why_interesting: one sentence of at most 30 words restating what the document says makes it matter (who needs it, stated scale or cost). No speculation.
- explicit_unsolved_signal: present is true only if the document itself says the problem is open, unsolved, a limitation, a challenge, or being sought. evidence is a verbatim quote of at most 50 words; an empty string when present is false.
- payment_signal: type is one of prize, grant, contract, hiring, investor_thesis, none_stated. A job posting for a role whose work is to solve the problem is hiring. stated is the amount, headcount or funding as written (empty string if none). evidence is a verbatim quote of at most 50 words supporting it; an empty string when type is none_stated. deadline is the stated submission or closing date as YYYY-MM-DD, or null.
- Quotes are copied character for character from the document text: no ellipses, no paraphrase, no merged fragments.
- technical_area: at most 3 short tags, e.g. "reinforcement learning", "protein design".
- entities: at most 3 organisations and 3 named researchers most directly connected to the problem.
- relevant_links: the numbers (from the numbered link list) of at most 5 links pointing to the official call, challenge, dataset, paper or organisation page about this problem; an empty list if none."""


def render_item(item: StoredItem, source: Source, category: Category) -> str:
    links = "\n".join(f"[{i}] {url}" for i, url in enumerate(item.links[:MAX_LINKS], 1))
    return (f'<document source_id="{source.id}" category="{category.id}" tier="{category.tier}">\n'
            f"<title>{item.title}</title>\n<url>{item.url}</url>\n<published>{item.published or ''}</published>\n"
            f"<text>\n{item.text}\n</text>\n<links>\n{links}\n</links>\n</document>")


def build_params(cfg: ExtractionCfg, item: StoredItem, source: Source, category: Category) -> dict:
    return {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "output_config": {"effort": cfg.effort, "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        "messages": [{"role": "user", "content": render_item(item, source, category)}],
    }


@dataclass
class ExtractContext:
    cfg: ExtractionCfg
    registry: Registry
    store: Store
    report: RunReport
    output_dir: Path
    run_id: str


def _fail(ctx: ExtractContext, item: StoredItem, error: str) -> None:
    ctx.store.mark_failed(item.item_id, error)
    ctx.report.extract_stat(item.source_id).failed += 1
    ctx.report.failures.append({"source_id": item.source_id, "item_id": item.item_id, "error": error})


def _required_quotes(c) -> tuple[list[str], bool]:
    """Quotes that must be found in the source, and whether none of them is empty."""
    required = []
    if c.explicit_unsolved_signal.present:
        required.append(c.explicit_unsolved_signal.evidence)
    if c.payment_signal.type != "none_stated":
        required.append(c.payment_signal.evidence)
    return required, all(bool(q) for q in required)


def handle_message(ctx: ExtractContext, item: StoredItem, message) -> None:
    stat = ctx.report.extract_stat(item.source_id)
    stat.items += 1
    usage = message.usage
    stat.output_tokens += usage.output_tokens
    stat.input_tokens += usage.input_tokens
    stat.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
    try:
        result = parse_structured(message, ExtractionResult)
    except ItemExtractionError as e:
        return _fail(ctx, item, str(e))
    source = ctx.registry.find(item.source_id)
    if source is None:
        return _fail(ctx, item, f"source {item.source_id!r} no longer in registry")
    category = ctx.registry.categories[source.category]
    now = utcnow()
    share = round(usage.output_tokens / len(result.candidates)) if result.candidates else 0
    for idx, c in enumerate(result.candidates):
        quotes, present = _required_quotes(c)
        verified = present and all(quote_in_text(q, item.text) for q in quotes)
        violations = length_violations(c)
        shown = item.links[:MAX_LINKS]
        referenced = [shown[n - 1] for n in dict.fromkeys(c.relevant_links) if 1 <= n <= len(shown)]
        unresolved = [n for n in c.relevant_links if not 1 <= n <= len(shown)]
        stat.unverified += int(not verified)
        stat.length_violations += int(bool(violations))
        record = {
            "source_id": source.id, "item_id": item.item_id,
            "candidate_id": f"cand-{item.item_id}-r{item.revision}-{idx}", "revision": item.revision,
            "source": {"url": item.url, "title": item.title, "date": item.published,
                       "tier": category.tier, "category": category.id},
            "candidate_problem": {"statement": c.statement},
            "why_interesting": c.why_interesting,
            "explicit_unsolved_signal": c.explicit_unsolved_signal.model_dump(),
            "payment_signal": c.payment_signal.model_dump(),
            "technical_area": c.technical_area,
            "entities": c.entities.model_dump(),
            "referenced_urls": referenced,  # resolved by code from relevant_links; the model never copies URLs
            "unresolved_link_refs": unresolved,
            "evidence_verified": verified,
            "length_violations": violations,
            "extracted_with": {"model": ctx.cfg.model, "run_id": ctx.run_id, "output_tokens": share, "at": iso(now),
                               "answered_by": getattr(message, "models_used", None) or [ctx.cfg.model]},
        }
        YamlStore(ctx.output_dir / now.strftime("%Y-%m")).save(record, record["candidate_id"])
    stat.candidates += len(result.candidates)
    if result.candidates:
        source.yield_.candidates += len(result.candidates)
        source.yield_.scans_since_candidate = 0
    else:
        stat.empty_output_tokens += usage.output_tokens
    ctx.store.mark_done(item.item_id)


def _params_for(ctx: ExtractContext, item: StoredItem) -> dict | None:
    source = ctx.registry.find(item.source_id)
    if source is None:
        _fail(ctx, item, f"source {item.source_id!r} no longer in registry")
        return None
    return build_params(ctx.cfg, item, source, ctx.registry.categories[source.category])


def _run_sync(ctx: ExtractContext, client, limit: int | None) -> None:
    items = _prioritized_pending(ctx, limit)
    log.info("extracting %d pending items (sync)", len(items))
    for i, item in enumerate(items, 1):
        stat = ctx.report.extract_stat(item.source_id)
        before = (stat.candidates, stat.failed, stat.output_tokens, len(ctx.report.failures))
        started = time.monotonic()
        _extract_one(ctx, client, item)
        took = time.monotonic() - started
        if stat.failed > before[1]:
            log.warning("[extract %d/%d] %s: %s -> FAILED %s (%.1fs)", i, len(items), item.source_id, item.title[:60],
                        ctx.report.failures[-1]["error"][:200], took)
        else:
            log.info("[extract %d/%d] %s: %s -> %d candidates, %d output tokens (%.1fs)", i, len(items),
                     item.source_id, item.title[:60], stat.candidates - before[0], stat.output_tokens - before[2], took)


def _extract_one(ctx: ExtractContext, client, item: StoredItem) -> None:
    params = _params_for(ctx, item)
    if params is None:
        return
    try:
        message = client.messages.create(**params)
    except anthropic.APIError as e:
        raise_if_not_transient(e)
        _fail(ctx, item, f"api: {e}")
        return
    except ItemExtractionError as e:
        _fail(ctx, item, str(e))
        return
    handle_message(ctx, item, message)


def _prioritized_pending(ctx: ExtractContext, limit: int | None) -> list[StoredItem]:
    """Pending items, highest source tier first (A: funded calls ... C: blogs); oldest first within a tier."""
    def tier(item: StoredItem) -> str:
        source = ctx.registry.find(item.source_id)
        return ctx.registry.categories[source.category].tier if source else "Z"
    items = sorted(ctx.store.pending(), key=tier)  # stable: keeps first_seen order within a tier
    return items if limit is None else items[:limit]


def run_extraction(ctx: ExtractContext, client, *, batch: bool, limit: int | None = None, sleep=time.sleep) -> None:
    if batch and isinstance(client, ClaudeCodeClient):
        raise ExtractionConfigError("batch extraction needs extraction.backend: api",
                                    fix="Use --sync, or switch the backend in config.yaml")
    try:
        if batch:
            _run_batch(ctx, client, limit, sleep)
        else:
            _run_sync(ctx, client, limit)
    finally:
        ctx.registry.save()


def recent_referenced_links(output_dir: Path, since: datetime) -> list[tuple[str, str]]:
    """(url, item_id) for the relevant links of candidates extracted since `since` (discovery input)."""
    out = []
    month = since.strftime("%Y-%m")
    for path in sorted(output_dir.glob("*/*.yaml")):
        if path.parent.name < month:
            continue
        rec = yaml.safe_load(path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(rec["extracted_with"]["at"]) >= since:
            out += [(url, rec["item_id"]) for url in rec.get("referenced_urls") or []]
    return out


def _collect_batch(ctx: ExtractContext, client, batch_id: str, sleep) -> None:
    try:
        while (b := client.messages.batches.retrieve(batch_id)).processing_status != "ended":
            counts = getattr(b, "request_counts", None)
            log.info("batch %s: %s%s; next check in %ds", batch_id, b.processing_status,
                     f" ({counts.processing} processing, {counts.succeeded} succeeded)" if counts else "",
                     ctx.cfg.batch_poll_seconds)
            sleep(ctx.cfg.batch_poll_seconds)
        log.info("batch %s ended; collecting results", batch_id)
        results = list(client.messages.batches.results(batch_id))
    except anthropic.NotFoundError as e:  # external: past the API's result retention, or another workspace
        for item in ctx.store.items_in_batch(batch_id).values():
            ctx.store.reset_pending(item.item_id)
        ctx.report.failures.append({"source_id": "*", "item_id": "*",
                                    "error": f"batch {batch_id} no longer available ({e}); its items were resubmitted"})
        return
    except anthropic.APIError as e:
        raise_if_not_transient(e)
        ctx.report.failures.append({"source_id": "*", "item_id": "*",
                                    "error": f"batch {batch_id} not collected (kept for next run): {e}"})
        return
    items = ctx.store.items_in_batch(batch_id)
    for r in results:
        item = items.pop(r.custom_id, None)
        if item is None:
            continue
        kind = r.result.type
        if kind == "succeeded":
            handle_message(ctx, item, r.result.message)
        elif kind == "errored" and r.result.error.error.type == "invalid_request_error":
            _fail(ctx, item, f"batch errored: {r.result.error}")
        else:  # canceled / expired / server-side error: external, retry next submission
            ctx.store.reset_pending(item.item_id)
    for item in items.values():  # no result returned for these
        ctx.store.reset_pending(item.item_id)


def _run_batch(ctx: ExtractContext, client, limit: int | None, sleep) -> None:
    for batch_id in ctx.store.submitted_batch_ids():
        _collect_batch(ctx, client, batch_id, sleep)
    requests = []
    for item in _prioritized_pending(ctx, limit):
        params = _params_for(ctx, item)
        if params is not None:
            requests.append(Request(custom_id=item.item_id, params=MessageCreateParamsNonStreaming(**params)))
    if not requests:
        return
    try:
        batch = client.messages.batches.create(requests=requests)
    except anthropic.APIError as e:
        raise_if_not_transient(e)
        ctx.report.failures.append({"source_id": "*", "item_id": "*", "error": f"batch submit failed (items stay pending): {e}"})
        return
    ctx.store.mark_submitted([r["custom_id"] for r in requests], batch.id)
    log.info("submitted batch %s with %d items", batch.id, len(requests))
    _collect_batch(ctx, client, batch.id, sleep)
