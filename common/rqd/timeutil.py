from datetime import date, datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def today() -> date:
    return utcnow().date()


def deadline_summary(deadlines, on: date) -> tuple[str | None, bool]:
    """(next deadline on or after `on`, whether every stated deadline has passed). Unparseable deadlines (e.g.
    "rolling") count as unknown, so a problem is only reported as all-passed when every deadline is known."""
    stated = [d for d in deadlines if d not in (None, "")]
    parsed: list[date | None] = []
    for d in stated:
        if isinstance(d, date):
            parsed.append(d)
            continue
        try:
            parsed.append(date.fromisoformat(str(d)))
        except ValueError:
            parsed.append(None)
    upcoming = sorted(p for p in parsed if p is not None and p >= on)
    return (upcoming[0].isoformat() if upcoming else None), bool(stated) and all(p is not None and p < on for p in parsed)
