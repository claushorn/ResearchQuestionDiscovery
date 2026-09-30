# Challenge Investigator — Design Spec

Date: 2026-09-30 · Status: approved in conversation · Revised 2026-09-30: headroom scraped, not an agent

## Purpose
For **finished challenges** SourceScout keeps (status `finished`; AIcrowd, DrivenData, Proteinbase), decide
whether it is worth trying to beat the best solution, and if so, find the best solutions and ask an agent for
improvement ideas.

1. **Headroom (gate, automatic, all unchecked finished challenges; deterministic)** — scrape the final leaderboard
   (AIcrowd `/leaderboards`, DrivenData `leaderboard_partial`; measured 2026-09-30: 38 of 42 finished challenges);
   winner = rank 1; direction = rank order checked against config `metric_bounds`, which also gives the ceiling by
   the metric's definition; baseline = the strongest organisers' baseline row, else (lower-is-better only) a small
   agent lookup whose value must be stated in a verified quote. Verdict `solved` (< threshold, default 10%),
   `headroom`, `unclear` (never `solved`), or `not_applicable` (no scraper for the source, e.g. Proteinbase, or no
   leaderboard page). An unrecognised layout fails that challenge (no silent fallback).
2. **Investigate (picked ids; refused for `solved` unless `--force`)** — best solutions (winners' / top teams'
   code, write-ups, papers, winners posts) and the agent's improvement ideas.

## Rules (no invented numbers, as EconomicValueInvestigator)
- Evidence quotes are fetched and verified (`rqd.verify`), min 3 words, boundary-matched.
- Headroom values: the scraped leaderboard or the metric's definition in config; a looked-up baseline needs a
  verified quote containing the figure. Unknown metric, rank order contradicting the metric's direction, unsorted
  leaderboard, winner beyond the ceiling or worse than the baseline → `unclear` + warning.
- Normalized headroom (code): higher-is-better `(ceiling − winner) / (ceiling − baseline)`, or
  `(ceiling − winner) / ceiling` without a baseline; lower-is-better `(winner − ceiling) / (baseline − ceiling)`,
  requires a baseline (else `unclear`). Winner beyond ceiling or non-positive scale → `unclear` + warning.
- Solutions: kept only with a verified evidence entry; a solution `score` is kept only if its figure is in its
  cited quote or the scraped leaderboard gives that team that score (else dropped + warning).
- Ideas are hypotheses: `expected_gain_assumption` is an explicitly labelled assumption; any other decimal or
  percentage in the text fields that appears in no verified quote → `warnings.unsupported_numbers`.
- Model-facing schemas flat; searches counted from tool calls; transcripts kept; history on re-runs.

## Shared code
`economicvalue/money.py` and EV's figure-in-quote check move to `rqd/numbers.py` (`parse_amounts`, `figures`,
`to_usd`, `figure_in_quote`, `numbers_in_text`); EV imports them. `sourcescout.store.Store.finished_items()`
lists finished items.

## Layout & commands
`ChallengeInvestigator/` (config.yaml, challenge_schema.yaml, README, `challengeinvestigator/`, tests
`test_ci_*.py` + `ci_testing.py`, `challenges/<item_id>.yaml`, `data/` git-ignored), CLI `challenges`:
```
uv run challenges headroom [<item-id> ...]      # default: every finished challenge not yet checked
uv run challenges investigate <item-id> [...] [--force]
uv run challenges list                          # verdict, headroom %, winner/metric, investigated?, title
uv run challenges show <item-id>
```
Config: `leaderboard_sources` (source id → scraper), `metric_bounds` (regex, direction, ceiling, definition),
`baseline_agent` (effort low, max_budget_usd 0.3, min_searches 1), `investigate_agent` (effort medium, 2.0, 4),
`headroom_threshold: 0.10`, `http`, `sourcescout_root`.

## Record `challenges/<item_id>.yaml`
See `ChallengeInvestigator/challenge_schema.yaml` (per-stage `headroom` and `investigation` blocks).
