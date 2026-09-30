from pathlib import Path

import typer
import yaml

from opportunitygenerator.config import DEFAULT_ROOT, OGConfig, OGPaths, load_config
from opportunitygenerator.run import OGContext, generate as run_generate, stale_inputs
from rqd.claude_code import make_client
from rqd.cli import clean_errors, exclusive, load_repo_env, progress_to_stderr
from rqd.errors import RqdError
from rqd.http import Fetcher

app = typer.Typer(no_args_is_help=True,
                  help="OpportunityGenerator: opportunity profile, thesis, recommendation and research brief per problem.")


def make_agent_client():
    return make_client("claude_code")


def make_fetcher_for(cfg: OGConfig) -> Fetcher:
    return Fetcher(cfg.http)


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="OpportunityGenerator directory")):
    load_repo_env(root)
    progress_to_stderr("opportunitygenerator")
    ctx.obj = root


def _open(root: Path) -> OGContext:
    paths = OGPaths(root)
    cfg = load_config(paths.config)
    return OGContext.open(paths, cfg, make_agent_client(), make_fetcher_for(cfg))


@app.command()
@clean_errors
@exclusive
def generate(ctx: typer.Context, problem_ids: list[str] = typer.Argument(..., help="problems with a fit (`fit list`)")):
    """One agent session per problem -> opportunities/OPP-NNNN.yaml + briefs/OPP-NNNN.md."""
    og = _open(ctx.obj)
    failures = run_generate(og, problem_ids)
    for pid, error in failures.items():
        typer.echo(f"FAILED {pid}: {error}")
    if failures:
        raise typer.Exit(1)


def _s(x) -> str:
    return "?" if x is None else str(x)


@app.command("list")
@clean_errors
def list_opportunities(ctx: typer.Context):
    """One line per opportunity: id, recommendation, N(ovelty) V(alue) T(ractability) F(it), stale inputs, title."""
    og = _open(ctx.obj)
    recs = og.opportunities.all() if og.opportunities.dir.is_dir() else []
    order = {"investigate": 0, "contact": 1, "ignore": 2}
    for r in sorted(recs, key=lambda r: (order[r["recommendation"]], r["id"])):
        p = r["opportunity_profile"]
        stale = stale_inputs(og, r)
        typer.echo(f"{r['id']}  {r['recommendation']:<11} N{_s(p['novelty'])} V{_s(p['economic_value'])} "
                   f"T{p['tractability']} F{p['personal_advantage']}"
                   f"{'  STALE: ' + ', '.join(stale) if stale else ''}  {r['title'][:80]}")
    typer.echo(f"{len(recs)} opportunities")


@app.command()
@clean_errors
def show(ctx: typer.Context, key: str = typer.Argument(..., help="OPP-NNNN or a problem id"),
         brief: bool = typer.Option(False, "--brief", help="print the research brief instead of the record")):
    """Print one opportunity record (or its brief)."""
    paths = OGPaths(ctx.obj)
    og = _open(ctx.obj)
    recs = og.opportunities.all() if og.opportunities.dir.is_dir() else []
    rec = next((r for r in recs if key in (r["id"], r["problem_id"])), None)
    if rec is None:
        raise RqdError(f"no opportunity {key}", fix="See `uv run opportunities list`")
    typer.echo((paths.briefs / f"{rec['id']}.md").read_text(encoding="utf-8") if brief
               else yaml.safe_dump(rec, sort_keys=False, allow_unicode=True))
