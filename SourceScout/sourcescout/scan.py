import logging
import re
import time
from datetime import datetime

from sourcescout.adapters import KINDS, RawItem
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher
from sourcescout.registry import Health, Registry, Source
from sourcescout.report import RunReport
from sourcescout.store import Store
from sourcescout.timeutil import iso

log = logging.getLogger("sourcescout")


def title_filter(source: Source, items: list[RawItem], job_title_include: str | None = None) -> tuple[list[RawItem], int]:
    """Deterministic pre-filter. Job boards without their own title_include use the config-wide pattern."""
    inc = source.params.get("title_include") or (job_title_include if source.category == "job_board" else None)
    exc = source.params.get("title_exclude")
    kept = [i for i in items
            if (not inc or re.search(inc, i.title)) and not (exc and re.search(exc, i.title))]
    return kept, len(items) - len(kept)


def scan(registry: Registry, store: Store, http: Fetcher, report: RunReport, *, now: datetime,
         max_item_chars: int, job_title_include: str | None = None, source_id: str | None = None, category: str | None = None,
         tier: str | None = None, force: bool = False) -> None:
    now_s = iso(now)
    sources = registry.scannable(now, source_id=source_id, category=category, tier=tier, force=force)
    log.info("scanning %d due sources", len(sources))
    for i, source in enumerate(sources, 1):
        log.info("[scan %d/%d] %s (%s) ...", i, len(sources), source.id, source.kind)
        started = time.monotonic()
        stat = report.scan_stat(source.id)
        source.last_scanned = now_s  # attempt time: a failing source is retried on its cadence, not every run
        item_errors: list[str] = []
        try:
            items = KINDS[source.kind].fetch(source, http, store.is_known, item_errors)
        except SourceFetchError as e:
            stat.error = str(e)
            source.health.consecutive_failures += 1
            source.health.last_error = str(e)
            log.warning("    %s: FAILED %s (%.1fs)", source.id, e, time.monotonic() - started)
            registry.save()  # per source: an interrupted scan keeps what it finished
            continue
        stat.item_errors = len(item_errors)
        report.failures += [{"source_id": source.id, "item_id": "-", "error": f"item fetch: {e}"} for e in item_errors]
        items, stat.filtered = title_filter(source, items, job_title_include)
        for item in items:
            status, truncated = store.upsert(item, now_s, max_item_chars)
            setattr(stat, status, getattr(stat, status) + 1)
            stat.truncated += int(truncated)
        source.health = Health(last_ok=now_s)
        source.yield_.scans += 1
        source.yield_.items_seen += len(items)
        if stat.new or stat.changed:  # zero-yield counts scans that gave the extractor something new
            source.yield_.scans_since_candidate += 1
        log.info("    %s: %d new, %d changed, %d unchanged, %d filtered, %d item errors (%.1fs)", source.id, stat.new,
                 stat.changed, stat.unchanged, stat.filtered, stat.item_errors, time.monotonic() - started)
        registry.save()
