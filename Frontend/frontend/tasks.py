"""Agent Tasks: one background process running a stage's own CLI on the selected ids. Output goes to
<data>/tasks/<id>.log; per-item results are parsed from the shared progress lines (rqd.investigation.run_each:
`[tag i/n] <id>: running ...`, `[tag i/n] <id> -> <summary> (Ns)`, `[tag i/n] <id> -> FAILED <reason>`) and a
clean error from `ERROR: <message>` / `Fix: <fix>` (rqd.cli.clean_errors)."""
import json
import os
import re
import signal
import subprocess
import threading
from pathlib import Path

from frontend.actions import ACTIONS, confirm
from frontend.db import connect
from rqd.cli import lock_held
from rqd.errors import RqdError
from rqd.timeutil import iso, utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, ids TEXT NOT NULL, refused TEXT NOT NULL,
  force INTEGER NOT NULL, argv TEXT NOT NULL, pid INTEGER, started TEXT NOT NULL, ended TEXT,
  status TEXT NOT NULL, exit_code INTEGER);
"""
# `[fit 1/2] prob-a: running (budget $1.50) ...`, `[fit 1/2] prob-a -> summary (12s)`, `[pe 1/2] cand-x (src) -> new (3.1s)`
PROGRESS = re.compile(r"\[[\w-]+ \d+/\d+\] (?P<id>\S+)(?: \([^)]*\))?(?:: running\b.*| -> (?P<result>.*))$")
DURATION = re.compile(r" \(\d+(?:\.\d+)?s\)$")


def parse_log(text: str) -> tuple[list[dict], tuple[str, str] | None]:
    """Per-item states in first-seen order, and the command's clean error (message, fix) if it printed one."""
    items: dict[str, dict] = {}
    error = None
    lines = text.splitlines()
    for n, line in enumerate(lines):
        m = PROGRESS.search(line)
        if m:
            result = m.group("result")
            if result is None:
                items[m.group("id")] = {"id": m.group("id"), "state": "running", "result": ""}
            elif result.startswith("FAILED "):
                items[m.group("id")] = {"id": m.group("id"), "state": "failed", "result": result.removeprefix("FAILED ")}
            else:
                items[m.group("id")] = {"id": m.group("id"), "state": "done", "result": DURATION.sub("", result)}
        elif line.startswith("ERROR: "):
            fix = lines[n + 1].removeprefix("Fix: ") if n + 1 < len(lines) and lines[n + 1].startswith("Fix: ") else ""
            error = (line.removeprefix("ERROR: "), fix)
    return list(items.values()), error


class TaskRunner:
    def __init__(self, data_dir: Path, roots: dict[str, Path], bin_dir: Path):
        self.data_dir, self.roots, self.bin_dir = data_dir, roots, bin_dir
        self.logs = data_dir / "tasks"
        self._db = connect(data_dir / "frontend.db")
        self._db.executescript(_SCHEMA)
        self._procs: dict[int, subprocess.Popen] = {}
        self._cancelled: set[int] = set()
        self._lock = threading.Lock()

    def reconcile(self) -> None:
        """At server start: tasks recorded as running whose process is gone ended while the server was down."""
        for tid, pid in self._db.execute("SELECT id, pid FROM tasks WHERE status='running'").fetchall():
            if not _alive(pid):
                with self._db:
                    self._db.execute("UPDATE tasks SET status='interrupted', ended=? WHERE id=?", (iso(utcnow()), tid))

    def busy(self) -> str | None:
        """Why Run is unavailable: a running Agent Task, or a stage's run lock held by a command run elsewhere."""
        row = self._db.execute("SELECT id, action, pid FROM tasks WHERE status='running' ORDER BY id DESC").fetchone()
        if row and (row[0] in self._procs or _alive(row[2])):
            return f"Agent Task #{row[0]} is running ({ACTIONS[row[1]].label})"
        held = [root.name for root in self.roots.values() if lock_held(root)]
        if held:
            return f"a command started outside the frontend is running on {', '.join(held)}"
        return None

    def start(self, action: str, ids: list[str], force: bool) -> int:
        with self._lock:
            reason = self.busy()
            if reason:
                raise RqdError(f"busy: {reason}", fix="Wait for it to finish (or cancel it), then run again")
            c = confirm(self.roots, action, ids, force)
            if not c["runnable"]:
                raise RqdError(f"nothing to run: every selected item is refused ({len(c['refused'])})",
                               fix="See the reasons on the confirmation page; select other items or use the force option")
            a = ACTIONS[action]
            argv = a.argv(self.bin_dir, self.roots[a.stage], c["runnable"], force)
            with self._db:
                tid = self._db.execute(
                    "INSERT INTO tasks (action, ids, refused, force, argv, started, status) VALUES (?,?,?,?,?,?,?)",
                    (action, json.dumps(c["runnable"]), json.dumps(c["refused"]), int(force), json.dumps(argv),
                     iso(utcnow()), "running")).lastrowid
            self.logs.mkdir(parents=True, exist_ok=True)
            with open(self.logs / f"{tid}.log", "wb") as log:
                proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        start_new_session=True)  # own process group: cancel stops claude -p too
            self._procs[tid] = proc
            with self._db:
                self._db.execute("UPDATE tasks SET pid=? WHERE id=?", (proc.pid, tid))
            threading.Thread(target=self._wait, args=(tid, proc), daemon=True).start()
            return tid

    def _wait(self, tid: int, proc: subprocess.Popen) -> None:
        code = proc.wait()
        status = "cancelled" if tid in self._cancelled else "done" if code == 0 else "failed"
        with self._lock, self._db:
            self._db.execute("UPDATE tasks SET status=?, exit_code=?, ended=? WHERE id=?",
                             (status, code, iso(utcnow()), tid))
            self._procs.pop(tid, None)

    def cancel(self, tid: int) -> None:
        row = self._db.execute("SELECT pid, status FROM tasks WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise RqdError(f"no Agent Task #{tid}", fix="See the Agent Tasks page")
        if row[1] != "running":
            return
        self._cancelled.add(tid)
        try:
            os.killpg(row[0], signal.SIGTERM)
        except ProcessLookupError:
            pass

    def status(self, tid: int) -> dict:
        row = self._db.execute("SELECT id, action, ids, refused, force, argv, pid, started, ended, status, exit_code "
                               "FROM tasks WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise RqdError(f"no Agent Task #{tid}", fix="See the Agent Tasks page")
        log_path = self.logs / f"{tid}.log"
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        items, error = parse_log(log)
        keys = ("id", "action", "ids", "refused", "force", "argv", "pid", "started", "ended", "status", "exit_code")
        task = dict(zip(keys, row))
        task.update(ids=json.loads(task["ids"]), refused=json.loads(task["refused"]), argv=json.loads(task["argv"]),
                    force=bool(task["force"]), label=ACTIONS[task["action"]].label, items=items, error=error, log=log)
        return task

    def list(self, limit: int = 200) -> list[dict]:
        return [self.status(tid) for (tid,) in self._db.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT ?", (limit,))]

    def latest(self) -> dict | None:
        row = self._db.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1").fetchone()
        return self.status(row[0]) if row else None


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
