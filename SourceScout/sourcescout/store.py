import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sourcescout.adapters.base import RawItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  item_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  published TEXT,
  content_hash TEXT NOT NULL,
  text TEXT NOT NULL,
  links TEXT NOT NULL,
  truncated INTEGER NOT NULL,
  revision INTEGER NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  extract_status TEXT NOT NULL,   -- pending | submitted | done | failed | finished (never extracted)
  extract_error TEXT,
  batch_id TEXT,
  finished INTEGER NOT NULL DEFAULT 0  -- the source's listing marks it finished (e.g. an ended challenge)
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(extract_status);
"""

UpsertResult = Literal["new", "changed", "unchanged"]


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_")])
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", query, ""))


def item_id_for(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class StoredItem:
    item_id: str
    source_id: str
    url: str
    title: str
    published: str | None
    text: str
    links: list[str]
    revision: int
    truncated: bool
    extract_status: str
    batch_id: str | None
    finished: bool = False


def _row(r: sqlite3.Row) -> StoredItem:
    return StoredItem(r["item_id"], r["source_id"], r["url"], r["title"], r["published"], r["text"],
                      json.loads(r["links"]), r["revision"], bool(r["truncated"]), r["extract_status"], r["batch_id"],
                      bool(r["finished"]))


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        columns = {r["name"] for r in self._db.execute("PRAGMA table_info(items)")}
        if "finished" not in columns:  # schema migration for stores created before the finished flag
            with self._db:
                self._db.execute("ALTER TABLE items ADD COLUMN finished INTEGER NOT NULL DEFAULT 0")

    def is_known(self, url: str) -> bool:
        return self._db.execute("SELECT 1 FROM items WHERE item_id=?", (item_id_for(url),)).fetchone() is not None

    def upsert(self, item: RawItem, now: str, max_chars: int) -> tuple[UpsertResult, bool]:
        truncated = len(item.text) > max_chars
        text = item.text[:max_chars]
        digest = hashlib.sha256(text.encode()).hexdigest()
        iid = item_id_for(item.url)
        row = self._db.execute("SELECT content_hash FROM items WHERE item_id=?", (iid,)).fetchone()
        links = json.dumps(list(item.links))
        queued = "finished" if item.finished else "pending"  # finished items are kept but never extracted
        with self._db:
            if row is None:
                self._db.execute(
                    "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,NULL,NULL,?)",
                    (iid, item.source_id, item.url, item.title, item.published, digest, text, links,
                     int(truncated), now, now, queued, int(item.finished)))
                return "new", truncated
            if row["content_hash"] != digest:
                self._db.execute(
                    "UPDATE items SET title=?, published=?, content_hash=?, text=?, links=?, truncated=?, "
                    "revision=revision+1, last_seen=?, extract_status=?, extract_error=NULL, batch_id=NULL, finished=? "
                    "WHERE item_id=?",
                    (item.title, item.published, digest, text, links, int(truncated), now, queued, int(item.finished), iid))
                return "changed", truncated
            self._db.execute("UPDATE items SET last_seen=? WHERE item_id=?", (now, iid))
            if item.finished:
                self._mark_finished(iid)
            return "unchanged", truncated

    def _mark_finished(self, iid: str) -> None:
        self._db.execute("UPDATE items SET finished=1, extract_status=CASE WHEN extract_status='pending' "
                         "THEN 'finished' ELSE extract_status END WHERE item_id=?", (iid,))

    def mark_finished(self, url: str) -> None:
        """The listing now marks a known item finished: it leaves the extraction queue (done items keep their
        candidates, which ProblemExtractor skips)."""
        with self._db:
            self._mark_finished(item_id_for(url))

    def pending(self, limit: int | None = None) -> list[StoredItem]:
        rows = self._db.execute(
            "SELECT * FROM items WHERE extract_status='pending' ORDER BY first_seen, item_id LIMIT ?",
            (-1 if limit is None else limit,))
        return [_row(r) for r in rows]

    def finished_items(self) -> list[StoredItem]:
        """Items the source marks finished (e.g. ended challenges): kept for other uses, never extracted."""
        return [_row(r) for r in self._db.execute("SELECT * FROM items WHERE finished=1 ORDER BY first_seen, item_id")]

    def get(self, item_id: str) -> StoredItem | None:
        r = self._db.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone()
        return _row(r) if r else None

    def mark_submitted(self, item_ids: list[str], batch_id: str) -> None:
        with self._db:
            self._db.executemany("UPDATE items SET extract_status='submitted', batch_id=? WHERE item_id=?",
                                 [(batch_id, i) for i in item_ids])

    def submitted_batch_ids(self) -> list[str]:
        rows = self._db.execute("SELECT DISTINCT batch_id FROM items WHERE extract_status='submitted' ORDER BY batch_id")
        return [r["batch_id"] for r in rows]

    def items_in_batch(self, batch_id: str) -> dict[str, StoredItem]:
        rows = self._db.execute("SELECT * FROM items WHERE extract_status='submitted' AND batch_id=?", (batch_id,))
        return {r["item_id"]: _row(r) for r in rows}

    def _set(self, item_id: str, status: str, error: str | None) -> None:
        with self._db:
            self._db.execute("UPDATE items SET extract_status=?, extract_error=?, batch_id=NULL WHERE item_id=?",
                             (status, error, item_id))

    def mark_done(self, item_id: str) -> None:
        self._set(item_id, "done", None)

    def mark_failed(self, item_id: str, error: str) -> None:
        self._set(item_id, "failed", error)

    def reset_pending(self, item_id: str) -> None:
        self._set(item_id, "pending", None)

    def status_counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT extract_status, COUNT(*) AS n FROM items GROUP BY extract_status")
        return {r["extract_status"]: r["n"] for r in rows}

    def reset_failed(self) -> int:
        with self._db:
            return self._db.execute(
                "UPDATE items SET extract_status='pending', extract_error=NULL WHERE extract_status='failed'").rowcount

    def links_first_seen_since(self, since: str) -> list[tuple[str, str]]:
        rows = self._db.execute("SELECT item_id, links FROM items WHERE first_seen >= ?", (since,))
        return [(link, r["item_id"]) for r in rows for link in json.loads(r["links"])]
