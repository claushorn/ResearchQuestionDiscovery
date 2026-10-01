# Frontend

A local web app over the pipeline's stores: see what every stage produced, triage it, and run the next stage on a
selection as an **Agent Task**: the stage's own CLI command in the background, so budgets, refusals ("solved",
"no fit"), staleness, the run lock, transcripts and clean errors behave exactly as on the command line.

```bash
uv run frontend                  # http://127.0.0.1:8765/ (opens the browser)
uv run frontend --port 9000 --no-browser
uv run frontend --root <dir>     # another Frontend directory (its config.yaml and data/)
```

It binds to 127.0.0.1 only (no login): `host` in `config.yaml` cannot be changed.

## Pages

| Page | Shows | Run on the selection |
|---|---|---|
| Overview | per stage: count, waiting for the next stage, stale; a running task or an outside run | |
| Candidates | SourceScout candidates: source, tier, statement, payment, deadline, the problem it became | extraction (`problemextractor run --candidate ...`) |
| Problems | one row per problem with the funnel: sources, novelty, value range, fit, opportunity, stale / waiting; filters, sorting, paging | novelty, economic value, fit, generate opportunity |
| Problem dossier | sources -> problem -> novelty -> economic value -> fit -> opportunity, with every evidence quote's verification | the same, for this problem |
| Opportunities | OPP id, recommendation, N/V/T/F, stale inputs, title; the research brief | |
| Challenges | finished challenges: headroom verdict, winner, investigated?; detail with solutions and ideas | headroom, investigate |
| Agent Tasks | every run: stage, items, start / end, status, per-item results and failures, command output | cancel a running task |

Before any spend a confirmation shows the number of items, the stage's per-item budget cap, the worst case (items x
cap), the items the stage refuses and why (the stage's own check functions, with its fix), items that already have
a record (running again replaces it), and the force option where the CLI has one. One task runs at a time; Run is
disabled while a task runs or while a command started in a terminal holds a stage's run lock.

## Data

Pages read the stages' own stores on every request (no copy, no cache). A record that cannot be read is listed above
the table with its file, message and fix; the others still show. The frontend writes only `Frontend/data/`
(git-ignored): `frontend.db` (triage: shortlist / reject / note per item; the Agent Tasks log) and `tasks/<id>.log`
(each task's command output). Triage is never written into, or read by, the stages.

## Configuration (`config.yaml`)

`port`, `page_size` (table rows per page) and `roots`: the stage directories, relative to this directory. Each stage
still reads its own `config.yaml` (budgets, its input directories).
