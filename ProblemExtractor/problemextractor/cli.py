from pathlib import Path

import typer
import yaml

from problemextractor.config import DEFAULT_ROOT, PEPaths, load_config
from problemextractor.extract import PEContext, run_extraction
from problemextractor.records import SORT_KEYS, best_payment, best_tier, due_passed
from rqd.records import YamlStore
from rqd.timeutil import today
from rqd.claude_code import make_client
from rqd.cli import clean_errors, exclusive, hold_lock, load_repo_env, progress_to_stderr
from rqd.errors import RqdError

app = typer.Typer(no_args_is_help=True,
                  help="ProblemExtractor: precise, merged problem records from SourceScout candidates.")


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="ProblemExtractor directory")):
    load_repo_env(root)
    progress_to_stderr("problemextractor")
    ctx.obj = root


@app.command()
@clean_errors
@exclusive
def run(ctx: typer.Context, limit: int = typer.Option(None, help="Max candidates to process"),
        category: list[str] = typer.Option(None, "--category",
                                           help="Only these SourceScout source categories (repeatable), e.g. tech_blog"),
        candidate: list[str] = typer.Option(None, "--candidate",
                                            help="Only these candidate ids, in this order (repeatable)")):
    """Turn new SourceScout candidates into problem records (tier A first), or exactly the --candidate ids."""
    paths = PEPaths(ctx.obj)
    cfg = load_config(paths.config)
    pe = PEContext.open(paths, cfg)
    try:
        with hold_lock(pe.ss_root):  # SourceScout must not write its store/candidates while PE reads them
            run_extraction(pe, make_client(cfg.extraction.backend), limit, category or None, candidate or None)
    finally:
        typer.echo(pe.report.render(cfg.extraction.token_budget))
        typer.echo(f"\nReport saved: {pe.report.save(paths.runs)}")


@app.command("list")
@clean_errors
def list_problems(ctx: typer.Context, sort: str = typer.Option("sources", help="sources | tier")):
    """One line per problem: id, number of sources, best tier, payment signal, statement."""
    if sort not in SORT_KEYS:
        raise RqdError(f"unknown sort {sort!r}", fix="Use --sort sources or --sort tier")
    records = YamlStore(PEPaths(ctx.obj).problems).all()
    for r in sorted(records, key=SORT_KEYS[sort]):
        typer.echo(f"{r['problem_id']}  src={len(r['sources'])}  tier={best_tier(r)}  "
                   f"pay={best_payment(r)}{'  DUE PASSED' if due_passed(r, today()) else ''}  "
                   f"{r['problem']['precise_statement'][:100]}")
    typer.echo(f"{len(records)} problems")


@app.command()
@clean_errors
def show(ctx: typer.Context, problem_id: str):
    """Print one problem record."""
    store = YamlStore(PEPaths(ctx.obj).problems)
    if not store.exists(problem_id):
        raise RqdError(f"no problem {problem_id}", fix="See `uv run problemextractor list`")
    typer.echo(yaml.safe_dump(store.load(problem_id), sort_keys=False, allow_unicode=True))
