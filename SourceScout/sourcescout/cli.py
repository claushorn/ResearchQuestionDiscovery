from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import typer

from sourcescout.adapters import KINDS, REQUIRED_PARAMS
from sourcescout.categories import load_categories
from sourcescout.config import DEFAULT_ROOT, Config, Paths, load_config
from sourcescout.discover import discover as run_discover
from rqd.cli import clean_errors, exclusive, load_repo_env, progress_to_stderr
from rqd.errors import RqdError, SourceFetchError
from rqd.claude_code import make_client
from sourcescout.extract import ExtractContext, recent_referenced_links, run_extraction
from rqd.http import Fetcher
from sourcescout.lifecycle import apply_lifecycle
from sourcescout.registry import Health, Registry
from sourcescout.report import RunReport
from sourcescout.scan import scan as run_scan
from sourcescout.store import Store
from rqd.timeutil import iso, utcnow

app = typer.Typer(no_args_is_help=True, help="SourceScout: collect newly exposed, paid-for technical problems.")
sources_app = typer.Typer(no_args_is_help=True, help="Inspect and manage registry sources.")
app.add_typer(sources_app, name="sources")


@dataclass
class Env:
    paths: Paths
    config: Config
    registry: Registry
    store: Store
    http: Fetcher


def _env(root: Path) -> Env:
    paths = Paths(root)
    config = load_config(paths.config)
    registry = Registry.load(paths.registry, load_categories(paths.categories), REQUIRED_PARAMS)
    return Env(paths, config, registry, Store(paths.db), Fetcher(config.http))


@app.callback()
def main(ctx: typer.Context, root: Path = typer.Option(DEFAULT_ROOT, "--root", help="SourceScout directory")):
    load_repo_env(root)
    progress_to_stderr("sourcescout")
    ctx.obj = root


def _finish(env: Env, report: RunReport) -> None:
    report.lifecycle += apply_lifecycle(env.registry, env.config.lifecycle)
    report.item_states = env.store.status_counts()
    env.registry.save()
    path = report.save(env.paths.runs)
    typer.echo(report.render(env.config.extraction.token_budget_per_candidate))
    typer.echo(f"\nReport saved: {path}")


def _scan(env: Env, report: RunReport, now: datetime, **filters) -> None:
    run_scan(env.registry, env.store, env.http, report, now=now,
             max_item_chars=env.config.extraction.max_item_chars,
             job_title_include=env.config.scan.job_title_include, **filters)


def _extract(env: Env, report: RunReport, batch: bool | None, limit: int | None) -> None:
    ctx = ExtractContext(env.config.extraction, env.registry, env.store, report, env.paths.output, report.run_id)
    if batch is None:  # default follows the backend: batches only exist on the API
        batch = env.config.extraction.backend == "api"
    run_extraction(ctx, make_client(env.config.extraction.backend), batch=batch, limit=limit)


def _discover(env: Env, report: RunReport, since: datetime) -> None:
    run_discover(env.registry, env.http, env.config.discovery, recent_referenced_links(env.paths.output, since),
                 env.store.links_first_seen_since(iso(since)), report, env.paths.unmapped)


@app.command()
@clean_errors
@exclusive
def scan(ctx: typer.Context, source: str = typer.Option(None, help="Scan only this source id"),
         category: str = typer.Option(None), tier: str = typer.Option(None),
         force: bool = typer.Option(False, help="Ignore cadence")):
    """Fetch due sources and store new/changed items."""
    env, now = _env(ctx.obj), utcnow()
    report = RunReport.new(now)
    _scan(env, report, now, source_id=source, category=category, tier=tier, force=force)
    _finish(env, report)


@app.command()
@clean_errors
@exclusive
def extract(ctx: typer.Context, batch: bool = typer.Option(None, "--batch/--sync", help="Default: batch for backend api, sync for claude_code"),
            limit: int = typer.Option(None, help="Max items to extract"),
            retry_failed: bool = typer.Option(False, "--retry-failed", help="Return failed items to pending first")):
    """Extract candidates from pending items (Batches API by default)."""
    env = _env(ctx.obj)
    report = RunReport.new(utcnow())
    if retry_failed:
        typer.echo(f"{env.store.reset_failed()} failed items returned to pending")
    try:
        _extract(env, report, batch, limit)
    finally:
        _finish(env, report)


@app.command()
@clean_errors
@exclusive
def discover(ctx: typer.Context, days: float = typer.Option(1.0, help="Look back this many days")):
    """Propose new sources from recent items and candidates."""
    env, now = _env(ctx.obj), utcnow()
    report = RunReport.new(now)
    _discover(env, report, now - timedelta(days=days))
    _finish(env, report)


@app.command()
@clean_errors
@exclusive
def run(ctx: typer.Context, batch: bool = typer.Option(None, "--batch/--sync", help="Default: batch for backend api, sync for claude_code"),
        limit: int = typer.Option(None, help="Max items to extract")):
    """scan -> extract -> discover -> lifecycle -> report."""
    env, now = _env(ctx.obj), utcnow()
    report = RunReport.new(now)
    try:
        _scan(env, report, now)
        _extract(env, report, batch, limit)
        _discover(env, report, now)
    finally:  # the scan part of the report survives an aborted extraction
        _finish(env, report)


@app.command()
@clean_errors
def report(ctx: typer.Context, run_id: str = typer.Option(None, "--run-id")):
    """Print a saved run report (latest by default)."""
    paths = Paths(ctx.obj)
    path = paths.runs / f"{run_id}.json" if run_id else RunReport.latest(paths.runs)
    if path is None or not path.exists():
        raise RqdError("No run reports found", fix="Run `uv run sourcescout run` first")
    budget = load_config(paths.config).extraction.token_budget_per_candidate
    typer.echo(RunReport.load(path).render(budget))


@sources_app.command("list")
@clean_errors
def sources_list(ctx: typer.Context):
    env = _env(ctx.obj)
    for s in env.registry.sources:
        y = s.yield_
        typer.echo(f"{s.id:32} {s.status:9} {s.category:20} {s.kind:10} scans={y.scans} cand={y.candidates} "
                   f"fail={s.health.consecutive_failures}")


@sources_app.command("check")
@clean_errors
def sources_check(ctx: typer.Context, source_id: str):
    """Fetch one source without storing anything; prints what an extraction would see."""
    env = _env(ctx.obj)
    s = env.registry.get(source_id)
    item_errors: list[str] = []
    try:
        items = KINDS[s.kind].fetch(s, env.http, lambda url: False, item_errors)
    except SourceFetchError as e:
        raise RqdError(f"{source_id}: {e}", fix="Correct the url/params in registry.yaml or drop the source")
    typer.echo(f"{source_id}: {len(items)} items")
    for it in items[:3]:
        typer.echo(f"  - {it.title[:80]} | {it.url} | {len(it.text)} chars, {len(it.links)} links")
    for err in item_errors:  # same per-item handling as scan: the source stays usable
        typer.echo(f"  item error: {err}")


def _set_status(root: Path, source_id: str, status: str) -> None:
    env = _env(root)
    s = env.registry.get(source_id)
    s.status = status
    if status == "active":
        s.health = Health(last_ok=s.health.last_ok)
        s.yield_.scans_since_candidate = 0
    env.registry.save()
    typer.echo(f"{source_id}: {status}")


@sources_app.command("promote")
@clean_errors
@exclusive
def sources_promote(ctx: typer.Context, source_id: str):
    _set_status(ctx.obj, source_id, "active")


@sources_app.command("retire")
@clean_errors
@exclusive
def sources_retire(ctx: typer.Context, source_id: str):
    _set_status(ctx.obj, source_id, "retired")
