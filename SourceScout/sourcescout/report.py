import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from rqd.timeutil import iso


@dataclass
class ScanStat:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    filtered: int = 0
    truncated: int = 0
    item_errors: int = 0
    error: str | None = None


@dataclass
class ExtractStat:
    items: int = 0
    failed: int = 0
    candidates: int = 0
    output_tokens: int = 0
    empty_output_tokens: int = 0  # spent on items that yielded no candidate
    input_tokens: int = 0
    cache_read_tokens: int = 0
    unverified: int = 0
    length_violations: int = 0

    def tokens_per_candidate(self) -> float | None:
        """Budget metric: output tokens of items that produced candidates, per candidate."""
        return (self.output_tokens - self.empty_output_tokens) / self.candidates if self.candidates else None


@dataclass
class RunReport:
    run_id: str
    started: str
    scan: dict[str, ScanStat] = field(default_factory=dict)
    extract: dict[str, ExtractStat] = field(default_factory=dict)
    failures: list[dict[str, str]] = field(default_factory=list)
    lifecycle: list[str] = field(default_factory=list)
    discovered: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    discovery_errors: list[str] = field(default_factory=list)
    item_states: dict[str, int] = field(default_factory=dict)

    @classmethod
    def new(cls, now: datetime) -> "RunReport":
        return cls(run_id=now.strftime("%Y%m%dT%H%M%SZ"), started=iso(now))

    def scan_stat(self, source_id: str) -> ScanStat:
        return self.scan.setdefault(source_id, ScanStat())

    def extract_stat(self, source_id: str) -> ExtractStat:
        return self.extract.setdefault(source_id, ExtractStat())

    def budget_violations(self, budget: int) -> dict[str, float]:
        out = {sid: tpc for sid, st in self.extract.items()
               if (tpc := st.tokens_per_candidate()) is not None and tpc > budget}
        cands = sum(st.candidates for st in self.extract.values())
        if cands:
            total = sum(st.output_tokens - st.empty_output_tokens for st in self.extract.values()) / cands
            if total > budget:
                out["ALL"] = total
        return out

    def save(self, runs_dir: Path) -> Path:
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{self.run_id}.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "RunReport":
        d = json.loads(path.read_text(encoding="utf-8"))
        d["scan"] = {k: ScanStat(**v) for k, v in d["scan"].items()}
        d["extract"] = {k: ExtractStat(**v) for k, v in d["extract"].items()}
        return cls(**d)

    @staticmethod
    def latest(runs_dir: Path) -> Path | None:
        runs = sorted(runs_dir.glob("*.json")) if runs_dir.exists() else []
        return runs[-1] if runs else None

    def render(self, budget: int) -> str:
        lines = [f"Run {self.run_id} (started {self.started})", "", "SCAN"]
        lines.append(f"  {'source':32} {'new':>4} {'chg':>4} {'same':>5} {'filt':>5} {'trunc':>5} {'itemerr':>7}  error")
        for sid, s in sorted(self.scan.items()):
            lines.append(f"  {sid:32} {s.new:>4} {s.changed:>4} {s.unchanged:>5} {s.filtered:>5} {s.truncated:>5} "
                         f"{s.item_errors:>7}  {s.error or ''}")
        lines += ["", "EXTRACT"]
        lines.append(f"  {'source':32} {'items':>5} {'fail':>4} {'cand':>4} {'out_tok':>8} {'tok/cand':>8} "
                     f"{'empty_tok':>9} {'cache_rd':>8} {'unverif':>7} {'len_viol':>8}")
        for sid, e in sorted(self.extract.items()):
            tpc = e.tokens_per_candidate()
            tpc_s = f"{tpc:.0f}" if tpc is not None else "n/a"
            lines.append(f"  {sid:32} {e.items:>5} {e.failed:>4} {e.candidates:>4} {e.output_tokens:>8} "
                         f"{tpc_s:>8} {e.empty_output_tokens:>9} {e.cache_read_tokens:>8} {e.unverified:>7} {e.length_violations:>8}")
        violations = self.budget_violations(budget)
        lines += ["", f"BUDGET VIOLATIONS (> {budget} output tokens/candidate): "
                  + (", ".join(f"{k}={v:.0f}" for k, v in violations.items()) or "none")]
        lines += ["", "ITEM STATES (all runs): " + (", ".join(f"{k}={v}" for k, v in sorted(self.item_states.items())) or "n/a")]
        if self.item_states.get("failed"):
            lines.append("  failed items are not retried automatically: `sourcescout extract --retry-failed`")
        for title, entries in [("ITEM FAILURES", [f"{f['source_id']}/{f['item_id']}: {f['error']}" for f in self.failures]),
                               ("LIFECYCLE", self.lifecycle), ("DISCOVERED", self.discovered),
                               ("UNMAPPED (review discovered_unmapped.yaml)", self.unmapped),
                               ("DISCOVERY ERRORS", self.discovery_errors)]:
            lines += ["", f"{title}: {len(entries)}"] + [f"  {x}" for x in entries]
        return "\n".join(lines)
