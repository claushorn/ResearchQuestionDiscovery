from pathlib import Path

import typer
import yaml

from problemextractor.config import DEFAULT_ROOT, PEPaths, load_config
from problemextractor.extract import PEContext, run_extraction
from problemextractor.records import ProblemStore
from rqd.claude_code import make_client
from rqd.cli import clean_errors, exclusive, load_repo_env, progress_to_stderr
from rqd.errors import RqdError

app = typer.Typer(no_args_is_help=True,
                  help="ProblemExtractor: precise, merged problem records from SourceScout candidates.")
_TIER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="ProblemExtractor directory")):
    load_repo_env(root)
    progress_to_stderr("problemextractor")
    ctx.obj = root


@app.command()
@clean_errors
@exclusive
def run(ctx: typer.Context, limit: int = typer.Option(None, help="Max candidates to process")):
    """Turn new SourceScout candidates into problem records (tier A first)."""
    paths = PEPaths(ctx.obj)
    cfg = load_config(paths.config)
    pe = PEContext.open(paths, cfg)
    try:
        run_extraction(pe, make_client(cfg.extraction.backend), limit)
    finally:
        typer.echo(pe.report.render(cfg.extraction.token_budget))
        typer.echo(f"\nReport saved: {pe.report.save(paths.runs)}")


def _best_payment(record: dict) -> str:
    signals = [s["payment_signal"] for s in record["sources"] if s["payment_signal"]["type"] != "none_stated"]
    stated = [p for p in signals if p.get("stated")]
    return (stated[0]["stated"] if stated else signals[0]["type"]) if signals else "-"


@app.command("list")
@clean_errors
def list_problems(ctx: typer.Context, sort: str = typer.Option("sources", help="sources | tier")):
    """One line per problem: id, number of sources, best tier, payment signal, statement."""
    records = ProblemStore(PEPaths(ctx.obj).problems).all()
    best_tier = {r["problem_id"]: min((s["tier"] for s in r["sources"]), key=_TIER.get) for r in records}
    key = (lambda r: (-len(r["sources"]), _TIER[best_tier[r["problem_id"]]])) if sort == "sources" else \
          (lambda r: (_TIER[best_tier[r["problem_id"]]], -len(r["sources"])))
    for r in sorted(records, key=key):
        typer.echo(f"{r['problem_id']}  src={len(r['sources'])}  tier={best_tier[r['problem_id']]}  "
                   f"pay={_best_payment(r)}  {r['problem']['precise_statement'][:100]}")
    typer.echo(f"{len(records)} problems")


@app.command()
@clean_errors
def show(ctx: typer.Context, problem_id: str):
    """Print one problem record."""
    store = ProblemStore(PEPaths(ctx.obj).problems)
    if not store.exists(problem_id):
        raise RqdError(f"no problem {problem_id}", fix="See `uv run problemextractor list`")
    typer.echo(yaml.safe_dump(store.load(problem_id), sort_keys=False, allow_unicode=True))
