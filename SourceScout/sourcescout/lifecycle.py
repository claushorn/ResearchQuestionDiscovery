from sourcescout.config import LifecycleCfg
from sourcescout.registry import Registry


def apply_lifecycle(registry: Registry, cfg: LifecycleCfg) -> list[str]:
    """Promote/retire sources by the spec §3.7 rules. Returns one message per transition."""
    msgs = []
    for s in registry.sources:
        if s.status == "retired":
            continue
        reason = None
        if s.health.consecutive_failures >= cfg.max_consecutive_failures:
            reason = f"{s.health.consecutive_failures} consecutive failures (last: {s.health.last_error})"
        elif s.status == "candidate" and s.yield_.candidates > 0:
            s.status = "active"
            msgs.append(f"{s.id}: candidate -> active (first candidate after {s.yield_.scans} scans)")
        elif s.status == "candidate" and s.yield_.scans >= cfg.promote_within_scans:
            reason = f"no candidate in first {s.yield_.scans} scans"
        elif s.status == "active" and s.yield_.scans_since_candidate >= cfg.retire_zero_yield_active:
            reason = f"no candidate in last {s.yield_.scans_since_candidate} scans"
        if reason:
            msgs.append(f"{s.id}: {s.status} -> retired ({reason})")
            s.status = "retired"
    return msgs
