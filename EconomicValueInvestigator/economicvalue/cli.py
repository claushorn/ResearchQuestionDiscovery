from pathlib import Path

import typer
import yaml

from economicvalue.assess import EVContext, assess as run_assess
from economicvalue.config import DEFAULT_ROOT, EVConfig, EVPaths, load_config
from economicvalue.score import score_all
from rqd.claude_code import make_client
from rqd.cli import clean_errors, exclusive, load_repo_env, progress_to_stderr
from rqd.errors import RqdError
from rqd.http import Fetcher
from rqd.records import YamlStore

app = typer.Typer(no_args_is_help=True,
                  help="EconomicValueInvestigator: who cares, and is there money in it? Every amount has a basis.")


def make_agent_client():
    return make_client("claude_code")


def make_fetcher_for(cfg: EVConfig) -> Fetcher:
    return Fetcher(cfg.http)


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="EconomicValueInvestigator directory")):
    load_repo_env(root)
    progress_to_stderr("economicvalue")
    ctx.obj = root


def _usd(x) -> str:
    return f"{x:,.0f}" if x is not None else "-"


@app.command()
@clean_errors
def score(ctx: typer.Context):
    """Free: money already stated in each problem's sources (all problems), written to data/scores.yaml."""
    paths = EVPaths(ctx.obj)
    cfg = load_config(paths.config)
    problems = YamlStore((paths.root / cfg.problemextractor_root).resolve() / "problems").all()
    scores = score_all(problems, cfg.currency_rates_usd, cfg.default_currency_by_source)
    paths.scores.parent.mkdir(parents=True, exist_ok=True)
    paths.scores.write_text(yaml.safe_dump(scores, sort_keys=False, allow_unicode=True), encoding="utf-8")
    for s in scores:
        salary = "-" if not s["salary_range_usd"] else f"{_usd(s['salary_range_usd'][0])}-{_usd(s['salary_range_usd'][1])}"
        typer.echo(f"{s['problem_id']}  committed_usd={_usd(s['max_committed_usd'])}  salary_usd={salary}  "
                   f"src={s['sources']}  tier={s['best_tier']}  deadline={s['next_deadline'] or '-'}  {s['statement'][:70]}")
    typer.echo(f"{len(scores)} problems (fixed currency rates from config.yaml)")


def _pv(ev: dict) -> str:
    pv = ev["potential_value"]
    return "unknown" if pv == "unknown" else f"{_usd(pv['low'])}-{_usd(pv['high'])} USD/yr ({pv['status']})"


def _line(rec: dict) -> str:
    ev = rec["economic_value"]
    flag = "" if rec["search"]["sufficient"] else "  INSUFFICIENT SEARCH"
    warn = sum(len(v) for v in rec["warnings"].values())
    return (f"{rec['problem_id']}  potential={_pv(ev)}  pain={ev['pain']['score']}  urgency={ev['urgency']['level']}  "
            f"buyer={ev['buyer'][:30]}  warnings={warn}  gate={rec['gate']}{flag}")


@app.command()
@clean_errors
@exclusive
def assess(ctx: typer.Context, problem_ids: list[str] = typer.Argument(..., help="ids from `problemextractor list`"),
           force: bool = typer.Option(False, "--force", help="Assess even if NoveltyInvestigator marked it solved")):
    """Who cares and is there money in it? Evidence-backed estimates for picked problems."""
    paths = EVPaths(ctx.obj)
    cfg = load_config(paths.config)
    ev = EVContext.open(paths, cfg, make_agent_client(), make_fetcher_for(cfg))
    failures = run_assess(ev, problem_ids, force)
    for pid in problem_ids:
        if pid not in failures:
            typer.echo(_line(ev.assessments.load(pid)))
    for pid, error in failures.items():
        typer.echo(f"FAILED {pid}: {error}")
    if failures:
        raise typer.Exit(1)


@app.command("list")
@clean_errors
def list_assessments(ctx: typer.Context):
    """One line per assessed problem: potential value and its status, pain, urgency, buyer, warnings."""
    recs = YamlStore(EVPaths(ctx.obj).assessments).all()
    for rec in recs:
        typer.echo(_line(rec))
    typer.echo(f"{len(recs)} assessments")


@app.command()
@clean_errors
def show(ctx: typer.Context, problem_id: str):
    """Print one assessment."""
    store = YamlStore(EVPaths(ctx.obj).assessments)
    if not store.exists(problem_id):
        raise RqdError(f"no assessment for {problem_id}", fix="Run `uv run economicvalue assess <id>`")
    typer.echo(yaml.safe_dump(store.load(problem_id), sort_keys=False, allow_unicode=True))
