# EconomicValueInvestigator

**Who cares, and is there money in it?** Every amount in an assessment is backed by evidence, a labelled
assumption, or it is `unknown` — the agent cannot invent dollar figures.

```bash
uv run economicvalue score                      # free: money already stated in each problem's sources
uv run economicvalue assess <problem-id> [...]  # paid: evidence-backed assessment of problems you pick
uv run economicvalue list                       # potential value + status, pain, urgency, buyer, warnings
uv run economicvalue show <problem-id>
```

- **score** parses the payment signals SourceScout stored (award ceilings, prizes, salary ranges) with fixed,
  visible conversion rates (`config.yaml` → `currency_rates_usd`); amounts stated without a currency get one only
  via `default_currency_by_source`; unparseable statements are listed, never guessed.
- **assess** runs one `claude -p` agent session per problem (WebSearch/WebFetch, `agent.max_budget_usd`) that
  answers: who has this problem, how frequently, how expensive, what they do currently, what failure costs,
  could a solution be deployed, who controls the budget. It refuses problems NoveltyInvestigator marked
  `solved` unless `--force`.
- **No invented amounts:** amounts exist only as estimates with a basis — `source` or `analogous_company`
  (evidence page fetched, quote found on it, and the estimate's figures contained in that quote) or
  `explicit_assumption` (stated, including any derivation). Units cannot rescale a figure. Evidence `title` and
  `company` are labels from the model (only the quote is verified). Invalid rows are
  rejected and listed in `warnings`; a quantity without a valid basis is `unknown`.
  Potential value (USD/year) is computed by code from two models: **incident** = affected_units ×
  frequency_per_year × cost_per_occurrence × addressable_share (recurring operational problems) and **market** =
  buyer_count × annual_spend_per_buyer × addressable_share (problems bought as products, services or research
  programmes). A model is `unknown` if any factor is; its status is the weakest factor's. `potential_value` shows
  the better-supported model, or the range spanning both when equally supported (`model: incident|market|both`);
  both are kept in `potential_value_models`.
  Amounts in the text answers that appear in no verified quote are flagged (`warnings.unsupported_amounts`).
- Output: `assessments/<problem-id>.yaml` (format: `economic_value_schema.yaml`); transcripts in `data/transcripts/`.
