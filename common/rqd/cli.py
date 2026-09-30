import fcntl
import functools
import logging
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from rqd.errors import RqdError


def load_repo_env(root: Path) -> None:
    """Capability dirs sit in the repo root; its git-ignored .env holds ANTHROPIC_API_KEY."""
    load_dotenv(Path(root).parent / ".env", override=False)


def clean_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RqdError as e:
            typer.echo(f"ERROR: {e}", err=True)
            if e.fix:
                typer.echo(f"Fix: {e.fix}", err=True)
            raise typer.Exit(1)
    return wrapper


def exclusive(fn):
    """One mutating command per capability directory at a time (state, registry, API usage)."""
    @functools.wraps(fn)
    def wrapper(ctx: typer.Context, *args, **kwargs):
        lock_path = Path(ctx.obj) / "data" / "run.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise RqdError("another command is running on this directory",
                                 fix="Wait for it to finish (or stop it), then run again") from e
            return fn(ctx, *args, **kwargs)
    return wrapper


def progress_to_stderr(logger_name: str) -> None:
    """Progress lines go to stderr (timestamped); reports go to stdout."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    for h in [h for h in logger.handlers if getattr(h, "_rqd_cli", False)]:
        logger.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    handler._rqd_cli = True
    logger.addHandler(handler)
