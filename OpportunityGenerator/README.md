# OpportunityGenerator

Combines technical novelty × economic value × tractability × personal advantage into an **opportunity profile**
(not one score), a thesis ("why this could be worth spending 10 hours investigating"), a recommendation and a
one-page **research brief**. The first stage allowed to say INVESTIGATE.

```bash
uv run opportunities generate <problem_id> [...]   # needs a fit (`fit assess`); novelty / EV optional
uv run opportunities list                          # OPP id, recommendation, N/V/T/F scores, STALE inputs, title
uv run opportunities show <OPP-id|problem_id> [--brief]
```
≈ $0.3–1.0 per problem (list-price equivalent on the subscription).

- **Copied, never re-rated:** personal advantage and its backed advantages (fit), novelty status, confidence and
  strongest counterargument (NoveltyInvestigator), beneficiary, buyer and potential value (EconomicValueInvestigator).
  A stage that has not run appears as "not checked" / "not assessed" and its score is null.
- **Rules (code):** the novelty score is null when novelty is unchecked or unclear, ≤ 3 when solved, ≤ 7 when
  partially solved; the value score is null exactly when EV is missing — violations reject the output.
  Recommendation: `ignore` unless personal advantage ≥ 7, tractability ≥ 5, and novelty / value (when known) ≥ 5 / 4
  (`thresholds` in `config.yaml`), and never for a solved problem; otherwise the model's investigate / contact.
- Evidence quotes are verified; numbers and money amounts no verified quote or earlier record states are listed in
  `warnings.unsupported_numbers` / `unsupported_amounts`; the first experiment's hours and $ are labelled assumptions.
- Before any spend, every input is checked: a missing or stale fit (made for an older problem revision), an unknown
  novelty status, a malformed upstream record or a stray file in `opportunities/` is a clean error with its fix.
  (A fit made with an older *profile* shows as STALE in `fit list`; re-run `fit assess` first.)
- Only verified quotes and the problem's stated (not `*_inferred`) fields back numbers — model prose never does.
- Output: `opportunities/OPP-NNNN.yaml` (format: `opportunity_schema.yaml`), `briefs/OPP-NNNN.md` — both git-ignored,
  because they quote the private profile.
