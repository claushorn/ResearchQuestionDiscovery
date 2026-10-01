# Frontend — Design Spec

Date: 2026-10-01
Status: approved in conversation; written for review

## 1. Purpose

One local place to **see** what every pipeline stage produced, **select** items, and **run the next stage** on the
selection — instead of seven CLIs. Single user (the repository owner), on this Mac only.

Decisions from the conversation:
- Local only: a web app on `127.0.0.1`, no login, no hosting. Stages must run locally anyway (`claude -p` on the
  user's subscription, local profile, local stores).
- Version 1 = the core loop + own triage. Later phases: run history & spend, sources page, company view, search,
  comparison, kanban, editing thresholds.
- Approach A: a Python web server inside this repository with server-rendered pages and light interactivity
  (selection, live progress). No JavaScript build step.
- The run log is called **Agent Tasks**.

## 2. Principles (from the project's rules)

- **No duplicated stage logic.** Stages run as the existing CLI commands in a background process, so budgets,
  "solved" refusals, staleness, the run lock, transcripts and clean errors behave exactly as on the command line.
- **One source of truth.** Pages read the stages' own stores (YAML records via `rqd.records.YamlStore`,
  SourceScout's `Store`, ProblemExtractor's state database) through their existing loaders and configs — no copy,
  no cache database. Every derived status (e.g. "waiting for the next stage", "stale") uses the stage's own
  function where one exists (`personalfit.run.is_stale`, `opportunitygenerator.run.stale_inputs`, …).
- **Frontend-owned data only:** triage decisions and the Agent Tasks log, in git-ignored `Frontend/data/`
  (added to the repo-layout guard test).
- **Clean errors:** a malformed record or a failed run is shown with the stage's own message and fix, never a
  traceback page.

## 3. Data model shown

Stages and links:

| Stage | Record | Key | Link to the next |
|---|---|---|---|
| Candidates (SourceScout) | `SourceScout/output/*/cand-*.yaml` | candidate_id | ProblemExtractor state (`processed`: candidate → problem, decision new/merged) |
| Problems | `ProblemExtractor/problems/*.yaml` | problem_id | — |
| Novelty | `NoveltyInvestigator/investigations/<problem_id>.yaml` | problem_id | |
| Economic value | `EconomicValueInvestigator/assessments/<problem_id>.yaml` | problem_id | |
| Fit | `PersonalFitInvestigator/fits/<problem_id>.yaml` | problem_id | |
| Opportunity | `OpportunityGenerator/opportunities/OPP-NNNN.yaml` (+ `briefs/`) | OPP id ↔ problem_id | |
| Challenges (side branch) | SourceScout finished items + `ChallengeInvestigator/challenges/*.yaml` | item_id | |

- **Waiting for:** derived from what exists (e.g. a candidate not processed → waiting for extraction; a problem
  with a fit and no opportunity → waiting for generate).
- **Stale:** from the stages' own staleness checks.
- **Triage** (frontend-owned): per item `shortlist | reject | none` and a free-text note, keyed by the item's id
  (candidate_id, problem_id, OPP id, challenge item_id). Shown and filterable on every page; never written into
  the stages' records and never read by the stages.

## 4. Running a stage (Agent Tasks)

- From a table: select rows → **Run <next stage>**. Available actions per page:
  - Candidates: *extract* (ProblemExtractor).
  - Problems: *novelty*, *economic value*, *fit*, *generate opportunity* (each only for problems where it applies).
  - Challenges: *headroom*, *investigate*.
- **Confirmation** before any spend: number of items, the stage's per-item budget cap and the worst case
  (items × cap), items that will be refused or skipped and why (e.g. "solved", "no fit", "already up to date"),
  and the stage's force option where it has one.
- **Execution:** one background process running the existing CLI command with the selected ids; its progress lines
  stream to an always-visible task panel; new records appear in the tables as items finish; per-item failures are
  listed with their reason; a task can be cancelled.
- **One task at a time** (the CLIs share a run lock): Run is disabled while a task is active — no queue in v1.
- **Agent Tasks page:** the log of tasks (stage, items, start/end, status, per-item results and failures, link to
  the command output). Spend totals are a later phase.
- **CLI gap to close:** ProblemExtractor's `run` selects by `--category` / `--limit` only; it gets a
  `--candidate <id>` option (repeatable) so selected candidates can be extracted.

## 5. Pages (version 1)

```
┌ Overview ─ Candidates ─ Problems ─ Opportunities ─ Challenges ─ Agent Tasks ┐
```
- **Overview:** per stage — count, waiting for the next stage, stale; the running task, if any.
- **Candidates:** table (source, category, tier, statement, payment signal, deadline / due passed, processed?),
  filters, triage, *extract* on selection.
- **Problems:** one row per problem with the funnel as columns — sources and best tier, novelty status, value
  range, fit score, opportunity recommendation, stale flags, triage. Filters (e.g. "has fit", "fit ≥ 7",
  "novelty open", "stale", "shortlisted") replace separate novelty / value / fit tables.
- **Problem dossier:** everything about one problem in pipeline order — its source candidates and links → the
  problem → novelty (closest work, counterargument) → economic value (estimates with their basis) → fit
  (advantages with profile file) → opportunity — with every evidence quote's verification badge and link; triage
  and the next-stage actions for this one problem.
- **Opportunities:** table (OPP id, recommendation, N/V/T/F, stale inputs, title), triage; **Brief** view renders
  `briefs/OPP-NNNN.md`.
- **Challenges:** finished challenges with headroom verdict, winner/metric, investigated?; *headroom* /
  *investigate* on selection; detail view with solutions and ideas.
- **Agent Tasks:** as in §4.

Tables handle hundreds of rows (the store already holds 500+ problems): server-side filtering, sorting and
paging.

## 6. Errors and edge cases

- A stage's records that fail to load are listed on the page (file, message, fix) while the other records show.
- A run that fails entirely (e.g. usage limit, not logged in) shows the CLI's clean error message and fix.
- If a CLI run is started outside the frontend, the lock makes Run unavailable and the Overview says so.
- Deleting / editing records is out of scope (the stages own them).

## 7. Testing

- Page ↔ store mapping on fixture stores (each stage, links, waiting / stale derivation reusing the stages'
  functions).
- Triage store (set, clear, filter) and its git-ignore guard.
- Task runner with a fake command: progress streaming, per-item results, cancel, lock respected.
- Confirmation content (counts, worst-case cost, refusals) per action.
- One end-to-end test: start a fake run from the Problems page and see the new record appear.
- ProblemExtractor `--candidate` option (test-first, in its package).

## 8. Later phases (not in version 1)

Run history with spend per stage / month; sources page (health, yield, promote / retire, `sources check`); company
view (which companies work on what, from talks / blogs / jobs); search across everything; side-by-side
opportunity comparison; kanban (discovered → investigating → contacted); editing thresholds in the UI;
notification when a long task finishes.
