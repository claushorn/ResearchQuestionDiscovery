# Challenge Investigator Implementation Plan

> Execute with superpowers:executing-plans. Spec: `docs/superpowers/specs/2026-09-30-challenge-investigator-design.md`.

**Global constraints:** `uv run`; atomic commits with the session trailers; TDD; shared code in `rqd`; flat
model-facing schemas; no number reaches a record without a verified quote containing it or a labelled
definition/assumption; tests `test_ci_*.py` + `ci_testing.py`, no conftest.

**Review focus:** (1) winner score not in its quote → `unclear`, never `solved`; (2) lower-is-better without
baseline → `unclear`; (3) investigate refuses `solved` before any spend; (4) idea text with an unquoted
percentage → flagged; (5) budget error on one challenge → next continues.

### Task 1 — `rqd/numbers.py` + `Store.finished_items()`
Move `economicvalue/money.py` → `rqd/numbers.py` (unchanged); move `_close`/`_in_quote` from `estimates.py`
→ `figure_in_quote(value, quote, kind)`; add `numbers_in_text(text) -> list[(value, is_percent)]` (decimals and
percentages only). EV imports; `test_ev_money.py` → `common/tests/test_rqd_numbers.py`. `Store.finished_items()`.
Tests first for `numbers_in_text` and `finished_items`; suite green; commit.

### Task 2 — headroom
`challengeinvestigator/{config,schema,prompt,headroom}.py`: flat `HeadroomOutput` (metric, direction, winner_team,
reasoning, confidence, evidence[], values[{quantity winner|ceiling|baseline, value, basis source|definition,
evidence, definition}]); `compute(out, verification, threshold) -> dict` (spec rules); `check(ctx, item)` agent
session + record. Tests: each rule (source/definition validity, figure-in-quote, best winner, formulas both
directions, missing baseline for lower-better, winner beyond ceiling, threshold edge), agent path with recorded
stream-json. Commit.

### Task 3 — investigate, CLI, docs
`InvestigateOutput` (evidence[], solutions[{place, team, title, url, kind, approach, score, evidence}],
ideas[{idea, builds_on, why_it_could_win, risks, effort, expected_gain_assumption}], summary); rules (solution
kept only with verified evidence; score figure check; number guard on idea text); gate (`solved` refused unless
`--force`, missing headroom → run headroom first); `cli.py` (`headroom`, `investigate`, `list`, `show`, lock);
README, schema doc, root README row, pyproject script, `.gitignore`. Tests incl. CLI. Commit.

### Task 4 — live, review, PR
Scan the challenge sources into a scratch copy; live headroom on all finished items; live investigate on one with
headroom; fresh whole-branch review; fix Critical/Important test-first; PR.
