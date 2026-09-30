# ProblemExtractor

Turns SourceScout candidates into **precise, merged problem records** — one file per distinct problem
(`problems/<problem-id>.yaml`, format: `problem_schema.yaml`), however many sources state it.
Document fields come from the source only (`"not stated"` instead of guessing), with the model's own expertise in separate `*_inferred` fields;
explicit unsolvedness quotes verified against the source text. It does not judge novelty, value or fit.

```bash
uv run problemextractor run [--limit N]     # process new SourceScout candidates (tier A first)
uv run problemextractor list [--sort tier]   # id, #sources, best tier, payment signal, DUE PASSED flag, statement
uv run problemextractor show <problem-id>
```

- **Merging:** a TF-IDF shortlist of the 5 most similar existing problems is offered to the model, which may
  merge the candidate into one of them (reason logged in `merge_log`, the candidate's own extraction kept).
  An id outside the shortlist is reported and treated as a new problem.
- **Deadlines:** calls stay collected after their proposal due date (still officially open, often re-solicited);
  `list` marks problems whose stated deadlines have all passed with `DUE PASSED`.
- **Idempotent:** processed candidates are remembered in `data/pe.db`; failed ones are retried next run.
- **Compute:** effort `high` and a higher limit than SourceScout: `extraction.token_budget` 2000 output
  tokens/candidate (measured at high effort: median 1297, p90 1752), reported per run with retries. Runs on the Claude
  subscription (`backend: claude_code`) by default.
- **Expert knowledge, labelled:** `known_solution` / `what_current_methods_cannot_do` hold what the document
  says (or `"not stated"`); `*_inferred` hold the model's own assessment of the state of the art where the
  document is silent. NoveltyInvestigator tests those claims with real searches.
- Measured 2026-09-30: nested objects in the model-facing schema made `claude -p` reject 3/10 outputs, so the
  model fills flat fields and code builds the nested record. Opus 5.5's biology safety classifier occasionally
  interrupts protein documents (one retry, external).
