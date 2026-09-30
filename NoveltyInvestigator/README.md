# NoveltyInvestigator

Adversarial: tries to **kill** a problem by finding evidence that it is already solved, merely an
implementation issue, has an obvious baseline, or that the obvious approaches were tried.
Runs only on problems you pick (`problemextractor list`).

```bash
uv run noveltyinvestigator investigate <problem-id> [<problem-id> ...]
uv run noveltyinvestigator list      # verdict, confidence, verified evidence, INSUFFICIENT SEARCH marker
uv run noveltyinvestigator show <problem-id>
```

- One `claude -p` agent session per problem (`WebSearch`, `WebFetch`; papers, GitHub, benchmarks, reports,
  patents, company publications), capped by `agent.max_budget_usd`; on the Claude subscription.
- Output (`investigations/<problem-id>.yaml`, format: `novelty_schema.yaml`): `novelty.status`, the six checks,
  `closest_work`, `difference_from_closest_work`, `strongest_counterargument`, `confidence`.
- **Evidence is checked by code:** every cited URL is fetched (HTML or PDF) and its quote looked up →
  `verified` / `quote_not_found` / `unfetchable`; `verified_fraction` summarises it.
- **Search is counted, not self-reported:** fewer than `agent.min_searches` WebSearch calls →
  `search.sufficient: false` (`INSUFFICIENT SEARCH` in `list`). Transcripts are kept in `data/transcripts/`.
- Re-investigating keeps earlier verdicts in `history`.
- Measured 2026-09-30: ~50–60 s and ~$0.25–0.30 list-price equivalent per investigation.
