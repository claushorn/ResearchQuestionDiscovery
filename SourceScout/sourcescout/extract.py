import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import anthropic
import yaml
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import ValidationError

from sourcescout.categories import Category
from sourcescout.config import ExtractionCfg
from sourcescout.errors import ExtractionConfigError
from sourcescout.registry import Registry, Source
from sourcescout.report import RunReport
from sourcescout.schema import EXTRACTION_SCHEMA, ExtractionResult, length_violations
from sourcescout.store import Store, StoredItem
from sourcescout.timeutil import iso, utcnow

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
- entities: organisations and named researchers mentioned in connection with the problem.
- referenced_urls: at most 5 URLs from the document's link list that point to the official call, challenge, dataset, or the organisation's own pages about the problem."""


def render_item(item: StoredItem, source: Source, category: Category) -> str:
    links = "\n".join(item.links[:50])
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


_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).translate(_QUOTES))
    return re.sub(r" ([.,;:!?)\]])", r"\1", s).strip()  # html_to_text puts inline tags on own lines


def quote_in_text(quote: str, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(text)


@dataclass
class ExtractContext:
    cfg: ExtractionCfg
    registry: Registry
    store: Store
    report: RunReport
    output_dir: Path
    run_id: str


def make_client() -> anthropic.Anthropic:
    client = anthropic.Anthropic()
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        raise ExtractionConfigError("No Anthropic credentials found",
                                    fix="export ANTHROPIC_API_KEY=... (or run `ant auth login`)")
    return client


def _fail(ctx: ExtractContext, item: StoredItem, error: str) -> None:
    ctx.store.mark_failed(item.item_id, error)
    ctx.report.extract_stat(item.source_id).failed += 1
    ctx.report.failures.append({"source_id": item.source_id, "item_id": item.item_id, "error": error})


def _raise_if_not_transient(e: anthropic.APIError) -> None:
    """Errors a retry cannot fix (auth, permission, bad model, bad request) abort the run."""
    if isinstance(e, (anthropic.APIConnectionError, anthropic.RateLimitError)):
        return
    if isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
        return
    raise ExtractionConfigError(f"Anthropic API rejected the request: {e}",
                                fix="Check credentials, the model name in config.yaml, and the request schema") from e


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
    if message.stop_reason in ("refusal", "max_tokens"):
        return _fail(ctx, item, f"stop_reason={message.stop_reason}")
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        return _fail(ctx, item, "no text block in response")
    try:
        result = ExtractionResult.model_validate_json(text)
    except ValidationError as e:
        return _fail(ctx, item, f"schema: {e.errors()[:3]}")
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
            "referenced_urls": c.referenced_urls,
            "evidence_verified": verified,
            "length_violations": violations,
            "extracted_with": {"model": ctx.cfg.model, "run_id": ctx.run_id, "output_tokens": share, "at": iso(now)},
        }
        out_dir = ctx.output_dir / now.strftime("%Y-%m")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{record['candidate_id']}.yaml").write_text(
            yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8")
    stat.candidates += len(result.candidates)
    if result.candidates:
        source.yield_.candidates += len(result.candidates)
        source.yield_.scans_since_candidate = 0
    ctx.store.mark_done(item.item_id)


def _params_for(ctx: ExtractContext, item: StoredItem) -> dict | None:
    source = ctx.registry.find(item.source_id)
    if source is None:
        _fail(ctx, item, f"source {item.source_id!r} no longer in registry")
        return None
    return build_params(ctx.cfg, item, source, ctx.registry.categories[source.category])


def _run_sync(ctx: ExtractContext, client, limit: int | None) -> None:
    for item in ctx.store.pending(limit):
        params = _params_for(ctx, item)
        if params is None:
            continue
        try:
            message = client.messages.create(**params)
        except anthropic.APIError as e:
            _raise_if_not_transient(e)
            _fail(ctx, item, f"api: {e}")
            continue
        handle_message(ctx, item, message)


def run_extraction(ctx: ExtractContext, client, *, batch: bool, limit: int | None = None, sleep=time.sleep) -> None:
    try:
        if batch:
            _run_batch(ctx, client, limit, sleep)
        else:
            _run_sync(ctx, client, limit)
    finally:
        ctx.registry.save()


def recent_references(output_dir: Path, since: datetime) -> list[tuple[str, str]]:
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
        while client.messages.batches.retrieve(batch_id).processing_status != "ended":
            sleep(ctx.cfg.batch_poll_seconds)
        results = list(client.messages.batches.results(batch_id))
    except anthropic.APIError as e:
        _raise_if_not_transient(e)
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
        elif kind == "errored":
            _fail(ctx, item, f"batch errored: {r.result.error}")
        else:  # canceled / expired: external, retry next submission
            ctx.store.reset_pending(item.item_id)
    for item in items.values():  # no result returned for these
        ctx.store.reset_pending(item.item_id)


def _run_batch(ctx: ExtractContext, client, limit: int | None, sleep) -> None:
    for batch_id in ctx.store.submitted_batch_ids():
        _collect_batch(ctx, client, batch_id, sleep)
    requests = []
    for item in ctx.store.pending(limit):
        params = _params_for(ctx, item)
        if params is not None:
            requests.append(Request(custom_id=item.item_id, params=MessageCreateParamsNonStreaming(**params)))
    if not requests:
        return
    try:
        batch = client.messages.batches.create(requests=requests)
    except anthropic.APIError as e:
        _raise_if_not_transient(e)
        ctx.report.failures.append({"source_id": "*", "item_id": "*", "error": f"batch submit failed (items stay pending): {e}"})
        return
    ctx.store.mark_submitted([r["custom_id"] for r in requests], batch.id)
    _collect_batch(ctx, client, batch.id, sleep)
