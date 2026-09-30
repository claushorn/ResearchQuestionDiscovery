from pathlib import Path

import typer
import yaml

from noveltyinvestigator.config import DEFAULT_ROOT, NIConfig, NIPaths, load_config
from noveltyinvestigator.investigate import NIContext, investigate as run_investigate
from rqd.claude_code import make_client
from rqd.cli import clean_errors, exclusive, load_repo_env, progress_to_stderr
from rqd.errors import RqdError
from rqd.http import Fetcher
from rqd.records import YamlStore

app = typer.Typer(no_args_is_help=True,
                  help="NoveltyInvestigator: adversarial search for evidence that a problem is already solved.")


def make_agent_client():
    return make_client("claude_code")  # web tools need the Claude Code agent (subscription)


def make_fetcher_for(cfg: NIConfig) -> Fetcher:
    return Fetcher(cfg.http)


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="NoveltyInvestigator directory")):
    load_repo_env(root)
    progress_to_stderr("noveltyinvestigator")
    ctx.obj = root


def _line(rec: dict, statement: str) -> str:
    flag = "" if rec["search"]["sufficient"] else "  INSUFFICIENT SEARCH"
    return (f"{rec['problem_id']}  {rec['novelty']['status']:<16} conf={rec['confidence']:.2f}  "
            f"verified={rec['verified_fraction']:.2f}  searches={rec['search']['searches']}{flag}  {statement[:80]}")


@app.command()
@clean_errors
@exclusive
def investigate(ctx: typer.Context, problem_ids: list[str] = typer.Argument(..., help="ids from `problemextractor list`")):
    """Try to kill each picked problem: search prior work, verify cited evidence, record the verdict."""
    paths = NIPaths(ctx.obj)
    cfg = load_config(paths.config)
    ni = NIContext.open(paths, cfg, make_agent_client(), make_fetcher_for(cfg))
    failures = run_investigate(ni, problem_ids)
    for pid in problem_ids:
        if pid not in failures:
            typer.echo(_line(ni.investigations.load(pid), ni.problems.load(pid)["problem"]["precise_statement"]))
    for pid, error in failures.items():
        typer.echo(f"FAILED {pid}: {error}")
    if failures:
        raise typer.Exit(1)


@app.command("list")
@clean_errors
def list_investigations(ctx: typer.Context):
    """One line per investigated problem: verdict, confidence, verified evidence, search sufficiency."""
    paths = NIPaths(ctx.obj)
    cfg = load_config(paths.config)
    problems = YamlStore((paths.root / cfg.problemextractor_root).resolve() / "problems")
    recs = YamlStore(paths.investigations).all()
    for rec in recs:
        pid = rec["problem_id"]
        statement = problems.load(pid)["problem"]["precise_statement"] if problems.exists(pid) else "(problem file missing)"
        typer.echo(_line(rec, statement))
    typer.echo(f"{len(recs)} investigations")


@app.command()
@clean_errors
def show(ctx: typer.Context, problem_id: str):
    """Print one investigation."""
    store = YamlStore(NIPaths(ctx.obj).investigations)
    if not store.exists(problem_id):
        raise RqdError(f"no investigation for {problem_id}", fix="Run `uv run noveltyinvestigator investigate <id>`")
    typer.echo(yaml.safe_dump(store.load(problem_id), sort_keys=False, allow_unicode=True))
