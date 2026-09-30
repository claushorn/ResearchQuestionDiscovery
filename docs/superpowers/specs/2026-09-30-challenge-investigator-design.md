# Challenge Investigator — Design Spec

Date: 2026-09-30 · Status: approved in conversation

## Purpose
For **finished challenges** SourceScout keeps (status `finished`; AIcrowd, DrivenData, Proteinbase), decide
whether it is worth trying to beat the best solution, and if so, find the best solutions and ask an agent for
improvement ideas.

1. **Headroom (gate, automatic, all unchecked finished challenges)** — metric, direction, winner score, ceiling,
   baseline; code computes normalized headroom; verdict `solved` (< threshold, default 10%), `headroom`, or
   `unclear` (winner or ceiling not backed). `unclear` is never `solved`.
2. **Investigate (picked ids; refused for `solved` unless `--force`)** — best solutions (winners' / top teams'
   code, write-ups, papers, winners posts) and the agent's improvement ideas.

## Rules (no invented numbers, as EconomicValueInvestigator)
- Evidence quotes are fetched and verified (`rqd.verify`), min 3 words, boundary-matched.
- `winner` and `baseline` values need basis `source`: the cited, verified quote must **contain the figure**.
- `ceiling` basis `source` (figure in quote) or `definition` (bounded metric stated, e.g. "accuracy ≤ 1"; recorded
  as a labelled definition). No assumed ceilings.
- Normalized headroom (code): higher-is-better `(ceiling − winner) / (ceiling − baseline)`, or
  `(ceiling − winner) / ceiling` without a baseline; lower-is-better `(winner − ceiling) / (baseline − ceiling)`,
  requires a baseline (else `unclear`). Winner beyond ceiling or non-positive scale → `unclear` + warning.
- Solutions: kept only with a verified evidence entry; a solution `score` is kept only if its figure is in its
  cited quote (else dropped + warning).
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
Config: `headroom_agent` (effort low, max_budget_usd 0.5, min_searches 1), `investigate_agent` (effort medium,
2.0, 4), `headroom_threshold: 0.10`, `http`, `sourcescout_root`.

## Record `challenges/<item_id>.yaml`
`challenge {title, url, source_id}`, `headroom {metric, direction, winner {value, team, basis}, ceiling {value,
basis}, baseline {..}|null, normalized_headroom, verdict, threshold, reasoning, confidence}`, `solutions [...]`,
`ideas [...]`, `evidence [...]`, `warnings`, `search`, `runs {headroom, investigate}`, `history`.
