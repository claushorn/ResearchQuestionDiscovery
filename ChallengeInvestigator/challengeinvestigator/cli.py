from pathlib import Path

import typer
import yaml

from challengeinvestigator.config import DEFAULT_ROOT, CIConfig, CIPaths, load_config
from challengeinvestigator.run import CIContext, _headline, check_headroom, investigate as run_investigate
from rqd.claude_code import make_client
from rqd.cli import clean_errors, exclusive, load_repo_env, progress_to_stderr
from rqd.errors import RqdError
from rqd.http import Fetcher
from rqd.records import YamlStore

app = typer.Typer(no_args_is_help=True,
                  help="ChallengeInvestigator: is a finished challenge worth beating, and how could we beat the best?")


def make_agent_client():
    return make_client("claude_code")


def make_fetcher_for(cfg: CIConfig) -> Fetcher:
    return Fetcher(cfg.http)


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="ChallengeInvestigator directory")):
    load_repo_env(root)
    progress_to_stderr("challengeinvestigator")
    ctx.obj = root


def _open(root: Path) -> CIContext:
    paths = CIPaths(root)
    cfg = load_config(paths.config)
    return CIContext.open(paths, cfg, make_agent_client(), make_fetcher_for(cfg))


@app.command()
@clean_errors
@exclusive
def headroom(ctx: typer.Context, item_ids: list[str] = typer.Argument(None, help="default: all unchecked finished challenges")):
    """Gate: metric, winner, ceiling, baseline -> normalized headroom and verdict (solved / headroom / unclear)."""
    failures = check_headroom(_open(ctx.obj), item_ids or None)
    for i, error in failures.items():
        typer.echo(f"FAILED {i}: {error}")
    if failures:
        raise typer.Exit(1)


@app.command()
@clean_errors
@exclusive
def investigate(ctx: typer.Context, item_ids: list[str] = typer.Argument(..., help="ids from `challenges list`"),
                force: bool = typer.Option(False, "--force", help="Investigate even if the headroom check found it solved")):
    """Best solutions + the agent's improvement ideas for picked challenges."""
    failures = run_investigate(_open(ctx.obj), item_ids, force)
    for i, error in failures.items():
        typer.echo(f"FAILED {i}: {error}")
    if failures:
        raise typer.Exit(1)


@app.command("list")
@clean_errors
def list_challenges(ctx: typer.Context):
    """One line per checked challenge: verdict and headroom, winner/metric, investigated?, title."""
    recs = YamlStore(CIPaths(ctx.obj).challenges).all()
    for r in sorted(recs, key=lambda r: -(r["headroom"]["normalized_headroom"] or -1)):
        h = r["headroom"]
        winner = f"{h['winner']['value']:g} {h['metric']}" if h["winner"] else f"? {h['metric']}"
        typer.echo(f"{r['item_id']}  {_headline(h):<14} winner={winner[:40]:<40} "
                   f"investigated={'yes' if r.get('investigation') else 'no'}  {r['challenge']['title'][:70]}")
    typer.echo(f"{len(recs)} challenges checked")


@app.command()
@clean_errors
def show(ctx: typer.Context, item_id: str):
    """Print one challenge record."""
    store = YamlStore(CIPaths(ctx.obj).challenges)
    if not store.exists(item_id):
        raise RqdError(f"no record for {item_id}", fix="Run `uv run challenges headroom`")
    typer.echo(yaml.safe_dump(store.load(item_id), sort_keys=False, allow_unicode=True))
