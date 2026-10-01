import sqlite3
from pathlib import Path

_SCHEMA = """CREATE TABLE IF NOT EXISTS processed (
  candidate_id TEXT PRIMARY KEY, problem_id TEXT NOT NULL, decision TEXT NOT NULL, at TEXT NOT NULL)"""


class PEState:
    """Which SourceScout candidates have been turned into (or merged into) a problem. Failures are not recorded,
    so a failed candidate is retried on the next run."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(_SCHEMA)

    def is_processed(self, candidate_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM processed WHERE candidate_id=?", (candidate_id,)).fetchone() is not None

    def record(self, candidate_id: str, problem_id: str, decision: str, at: str) -> None:
        with self._db:
            self._db.execute("INSERT INTO processed VALUES (?,?,?,?)", (candidate_id, problem_id, decision, at))

    def all(self) -> dict[str, tuple[str, str]]:
        """{candidate_id: (problem_id, decision)} for every processed candidate."""
        return {c: (p, d) for c, p, d in self._db.execute("SELECT candidate_id, problem_id, decision FROM processed")}
