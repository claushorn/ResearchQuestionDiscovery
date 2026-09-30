# ProblemExtractor

Turns SourceScout candidates into **precise, merged problem records** — one file per distinct problem
(`problems/<problem-id>.yaml`, format: `problem_schema.yaml`), however many sources state it.
It extracts from the source documents only: no outside knowledge, `"not stated"` instead of guessing,
explicit unsolvedness quotes verified against the source text. It does not judge novelty, value or fit.

```bash
uv run problemextractor run [--limit N]     # process new SourceScout candidates (tier A first)
uv run problemextractor list [--sort tier]   # id, #sources, best tier, payment signal, statement
uv run problemextractor show <problem-id>
```

- **Merging:** a TF-IDF shortlist of the 5 most similar existing problems is offered to the model, which may
  merge the candidate into one of them (reason logged in `merge_log`, the candidate's own extraction kept).
  An id outside the shortlist is reported and treated as a new problem.
- **Idempotent:** processed candidates are remembered in `data/pe.db`; failed ones are retried next run.
- **Cost:** `config.yaml` → `extraction.token_budget` (800 output tokens/candidate), reported per run with the
  number of structured-output retries. Runs on the Claude subscription (`backend: claude_code`) by default.
- Measured 2026-09-30: nested objects in the model-facing schema made `claude -p` reject 3/10 outputs, so the
  model fills flat fields and code builds the nested record. Opus 5.5's biology safety classifier occasionally
  interrupts protein documents (one retry, external).
