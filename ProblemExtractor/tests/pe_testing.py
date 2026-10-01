"""Helpers for ProblemExtractor tests (unique module name: no conftest collisions across capabilities)."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import yaml

from sourcescout.adapters.base import RawItem
from sourcescout.store import Store, item_id_for

ITEM_TEXT = "The agency seeks planning methods for warehouse robots, which remains an open challenge. Awards up to $1.5M."


def candidate(n: int = 0, statement: str = "Long-horizon planning for warehouse robots under uncertainty.",
              tier: str = "A", source_id: str = "grants-gov-ml", quote: str = "remains an open challenge",
              at: str = "2026-09-30T12:00:00+00:00") -> dict:
    item = item_id_for(f"https://g.example/{n}")
    return {"source_id": source_id, "item_id": item, "candidate_id": f"cand-{item}-r1-0", "revision": 1,
            "source": {"url": f"https://g.example/{n}", "title": f"Call {n}", "date": None, "tier": tier,
                       "category": "gov_solicitation"},
            "candidate_problem": {"statement": statement}, "why_interesting": "Agency funds it.",
            "explicit_unsolved_signal": {"present": bool(quote), "evidence": quote},
            "payment_signal": {"type": "grant", "stated": "$1.5M", "evidence": "up to $1.5M", "deadline": "2026-12-01"},
            "technical_area": ["planning"], "entities": {"organizations": ["NSF"], "researchers": []},
            "referenced_urls": [], "evidence_verified": True, "length_violations": [],
            "extracted_with": {"model": "m", "run_id": "R", "output_tokens": 400, "at": at}}


def pe_output(merge_with=None, statement="Plan long-horizon robot tasks under uncertainty.", explicit=True,
              evidence="remains an open challenge", known="not stated") -> dict:
    return {"merge_with": merge_with, "merge_reason": "same capability" if merge_with else "new",
            "precise_statement": statement, "known_solution": known,
            "what_current_methods_cannot_do": "plan beyond short horizons",
            "desired_capability": "reliable long-horizon plans", "why_it_matters": "the agency funds it",
            "unsolved_explicit": explicit, "explicit_evidence": evidence if explicit else "", "unsolved_inferred": False}


def seed(ss_root: Path, candidates: list[dict], text: str = ITEM_TEXT) -> None:
    """Write SourceScout candidate files and their source items, as SourceScout would."""
    store = Store(ss_root / "data" / "scout.db")
    out = ss_root / "output" / "2026-09"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[2] / "SourceScout" / "sources.yaml", ss_root / "sources.yaml")
    for c in candidates:
        store.upsert(RawItem(c["source_id"], c["source"]["url"], c["source"]["title"], None, text, ()),
                     "2026-09-30T00:00:00+00:00", 20000)
        (out / f"{c['candidate_id']}.yaml").write_text(yaml.safe_dump(c, sort_keys=False))


def message(payload: dict, output_tokens: int = 420):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))], stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=2000, output_tokens=output_tokens, cache_read_input_tokens=0))


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **params):
        self.calls.append(params)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
