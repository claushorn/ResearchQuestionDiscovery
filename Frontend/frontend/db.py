"""The frontend's own data (git-ignored Frontend/data/frontend.db): triage decisions. Never written into the
stages' records and never read by the stages."""
import sqlite3
from pathlib import Path

from rqd.timeutil import iso, utcnow

KINDS = ("candidate", "problem", "opportunity", "challenge")
STATUSES = ("shortlist", "reject", "none")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS triage (
  kind TEXT NOT NULL, item_id TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL, at TEXT NOT NULL,
  PRIMARY KEY (kind, item_id));
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.executescript(_SCHEMA)
    return db


class Triage:
    def __init__(self, path: Path):
        self._db = connect(path)

    def set(self, kind: str, item_id: str, status: str, note: str) -> None:
        """status none with no note clears the item."""
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r} (one of {', '.join(KINDS)})")
        if status not in STATUSES:
            raise ValueError(f"unknown triage status {status!r} (one of {', '.join(STATUSES)})")
        with self._db:
            if status == "none" and not note.strip():
                self._db.execute("DELETE FROM triage WHERE kind=? AND item_id=?", (kind, item_id))
            else:
                self._db.execute("INSERT OR REPLACE INTO triage VALUES (?,?,?,?,?)",
                                 (kind, item_id, status, note.strip(), iso(utcnow())))

    def get_all(self, kind: str) -> dict[str, dict]:
        return {i: {"status": s, "note": n} for i, s, n in
                self._db.execute("SELECT item_id, status, note FROM triage WHERE kind=?", (kind,))}

    def get_many(self, kind: str, ids: list[str]) -> dict[str, dict]:
        everything = self.get_all(kind)
        return {i: everything[i] for i in ids if i in everything}
