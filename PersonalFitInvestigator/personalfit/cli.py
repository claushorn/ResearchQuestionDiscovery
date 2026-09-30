from pathlib import Path

import typer
import yaml

from personalfit.config import DEFAULT_ROOT, PFPaths, load_config
from personalfit.run import PFContext, assess as run_assess, is_stale
from rqd.claude_code import make_client
from rqd.cli import clean_errors, exclusive, load_repo_env, progress_to_stderr
from rqd.errors import RqdError
from rqd.records import YamlStore

app = typer.Typer(no_args_is_help=True,
                  help="PersonalFitInvestigator: what advantage would this profile have over a strong ML researcher?")


def make_agent_client():
    return make_client("claude_code")


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="PersonalFitInvestigator directory")):
    load_repo_env(root)
    progress_to_stderr("personalfit")
    ctx.obj = root


def _open(root: Path) -> PFContext:
    paths = PFPaths(root)
    return PFContext.open(paths, load_config(paths.config), make_agent_client())


@app.command()
@clean_errors
@exclusive
def assess(ctx: typer.Context, problem_ids: list[str] = typer.Argument(..., help="ids from `problemextractor list`")):
    """One agent call per problem: advantages (quoted from your profile), gaps, interest match, score 0-10."""
    failures = run_assess(_open(ctx.obj), problem_ids)
    for pid, error in failures.items():
        typer.echo(f"FAILED {pid}: {error}")
    if failures:
        raise typer.Exit(1)


@app.command("list")
@clean_errors
def list_fits(ctx: typer.Context):
    """One line per fit: score, number of backed advantages, stale?, problem statement."""
    pf = _open(ctx.obj)
    fits = pf.fits.all()
    for f in sorted(fits, key=lambda f: -f["personal_advantage"]["score"]):
        problem = pf.problems.load(f["problem_id"]) if pf.problems.exists(f["problem_id"]) else None
        stale = problem is None or is_stale(f, problem, pf.profile)
        statement = problem["problem"]["precise_statement"] if problem else "(problem removed)"
        typer.echo(f"{f['problem_id']}  {f['personal_advantage']['score']:>2}/10  advantages={len(f['advantages'])}"
                   f"{'  STALE' if stale else ''}  {statement[:90]}")
    typer.echo(f"{len(fits)} fits")


@app.command()
@clean_errors
def show(ctx: typer.Context, problem_id: str):
    """Print one fit record."""
    store = YamlStore(PFPaths(ctx.obj).fits)
    if not store.exists(problem_id):
        raise RqdError(f"no fit for {problem_id}", fix=f"Run `uv run fit assess {problem_id}`")
    typer.echo(yaml.safe_dump(store.load(problem_id), sort_keys=False, allow_unicode=True))
