# SourceScout

Collects *newly exposed technical problems that somebody has a reason to pay to solve* from funded calls,
challenge platforms, job boards, investor theses, engineering blogs and workshop calls. It extracts shallow
candidate records only — no value estimation or triage (later stages).

## Files
- `sources.yaml` — category classes (tier, enabled). Enable a category to scan its sources.
- `registry.yaml` — curated sources (config only; never written by the tools, so new sources arrive by PR).
- `data/registry_state.yaml` — runtime state per source (status, health, yield, last scan) and the sources
  `discover` added (git-ignored). A pre-split `registry.yaml` with inline state is migrated on the next save;
  then restore the tracked file with `git checkout -- SourceScout/registry.yaml`.
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
`finished_link_text` — entries the listing marks ended/closed, `finished_after_heading` — everything below e.g.
"Completed competitions", `finished_listing: true` — a listing of finished entries only). Finished entries are
stored with status `finished` (kept for later use, e.g. finding winners' solutions) but never extracted, and
ProblemExtractor never turns them into problems.
`page` (`content_selector`).
Industry talks, one item per talk: `json_sessions` (`items_path` — dotted path, `*` steps into every list element /
mapping value; `title_field`, `text_fields`, optional `embedded` — CSS selector of a `<script>` holding the JSON, e.g.
`script#__NEXT_DATA__`; `url_field` (relative paths resolve against the listing), `id_field`, `date_field`,
`max_items`) for pretalx schedule exports, sessions.json feeds and Next.js agendas; `html_sections`
(`section_selector` wrapping one talk, `title_selector`, `max_items`) for one static page listing many talks;
`doi_list` (`max_items`) for accepted-paper pages listing DOIs (e.g. KDD): one item per paper with title, abstract
and author institutions from OpenAlex (publisher pages such as ACM block scripts). Talks with a detail page per talk
(M3, T3chFest) use `html_list`, whose `link_selector` may use descendant selectors.
Talks are category `industry_talk`; their payment signal is `company_investment` (stated = the company), and only
limitations / open challenges the talk itself states make a candidate. Extract them with
`uv run problemextractor run --category industry_talk`.
Every kind accepts `title_include` / `title_exclude` regexes; job boards without
`title_include` use `scan.job_title_include` from `config.yaml`.

## Lifecycle
Discovered sources start as `candidate`; promoted on their first candidate, retired after
`promote_within_scans` scans without one. Active sources are retired after `retire_zero_yield_active`
scans without a candidate or `max_consecutive_failures` failed fetches. `sources promote|retire` overrides.
