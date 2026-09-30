# SourceScout

Collects *newly exposed technical problems that somebody has a reason to pay to solve* from funded calls,
challenge platforms, job boards, investor theses, engineering blogs and workshop calls. It extracts shallow
candidate records only — no value estimation or triage (later stages).

## Files
- `sources.yaml` — category classes (tier, enabled). Enable a category to scan its sources.
- `registry.yaml` — concrete sources (rewritten by the tool; comments are not preserved).
- `config.yaml` — model, effort, token budget, lifecycle and HTTP settings.
- `output/YYYY-MM/*.yaml` — one candidate per file (format: `scout_output_schema.yaml`).
- `data/` — SQLite item store and run reports (not versioned).
- `discovered_unmapped.yaml` — discovered URLs that fit no category; review by hand.

## Usage
```bash
# extraction.backend in config.yaml: claude_code (default; `claude -p` on your Claude subscription, sync)
# or api (ANTHROPIC_API_KEY from ResearchQuestionDiscovery/.env or the environment; batches, pay per token)
uv run sourcescout run                  # scan -> extract -> discover -> report
uv run sourcescout run --limit 5       # small run (sync on claude_code, batch on api)
uv run sourcescout scan --tier A --force
uv run sourcescout sources list
uv run sourcescout sources check <id>   # dry fetch of one source
uv run sourcescout report               # latest run report
uv run sourcescout extract --retry-failed  # return failed items to pending
```

## Progress and re-runs
Progress goes to stderr (one line per source while scanning, one per item while extracting, batch polls);
the report goes to stdout. Re-running is incremental: sources within their cadence are not fetched,
unchanged items are not re-extracted, and `--limit N` leaves the rest `pending` for the next run.
Only one mutating command runs per SourceScout directory at a time (`data/run.lock`).

## Source kinds
`rss` (params: `max_items`, `fetch_full`), `greenhouse`, `lever`, `ashby`, `grants_gov` (`keyword`, `rows`,
`opp_statuses`), `html_list` (`link_selector`, `link_pattern`, `max_items`, `content_selector`,
`skip_link_text` — skip listing entries marked finished, `stop_at_heading` — ignore everything below e.g. "Completed competitions"),
`page` (`content_selector`). Every kind accepts `title_include` / `title_exclude` regexes; job boards without
`title_include` use `scan.job_title_include` from `config.yaml`.

## Lifecycle
Discovered sources start as `candidate`; promoted on their first candidate, retired after
`promote_within_scans` scans without one. Active sources are retired after `retire_zero_yield_active`
scans without a candidate or `max_consecutive_failures` failed fetches. `sources promote|retire` overrides.
