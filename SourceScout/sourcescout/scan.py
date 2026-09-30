import re
from datetime import datetime

from sourcescout.adapters import KINDS, RawItem
from sourcescout.errors import SourceFetchError
from sourcescout.http import Fetcher
from sourcescout.registry import Health, Registry, Source
from sourcescout.report import RunReport
from sourcescout.store import Store
from sourcescout.timeutil import iso


def title_filter(source: Source, items: list[RawItem]) -> tuple[list[RawItem], int]:
    inc = source.params.get("title_include")
    exc = source.params.get("title_exclude")
    kept = [i for i in items
            if (not inc or re.search(inc, i.title)) and not (exc and re.search(exc, i.title))]
    return kept, len(items) - len(kept)


def scan(registry: Registry, store: Store, http: Fetcher, report: RunReport, *, now: datetime,
         max_item_chars: int, source_id: str | None = None, category: str | None = None,
         tier: str | None = None, force: bool = False) -> None:
    now_s = iso(now)
    for source in registry.scannable(now, source_id=source_id, category=category, tier=tier, force=force):
        stat = report.scan_stat(source.id)
        try:
            items = KINDS[source.kind].fetch(source, http, store.is_known)
        except SourceFetchError as e:
            stat.error = str(e)
            source.health.consecutive_failures += 1
            source.health.last_error = str(e)
            continue
        items, stat.filtered = title_filter(source, items)
        for item in items:
            status, truncated = store.upsert(item, now_s, max_item_chars)
            setattr(stat, status, getattr(stat, status) + 1)
            stat.truncated += int(truncated)
        source.health = Health(last_ok=now_s)
        source.last_scanned = now_s
        source.yield_.scans += 1
        source.yield_.items_seen += len(items)
        source.yield_.scans_since_candidate += 1
    registry.save()
