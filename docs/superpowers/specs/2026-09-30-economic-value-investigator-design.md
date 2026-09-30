# Economic Value Investigator — Design Spec

Date: 2026-09-30
Status: approved in conversation; written for review
Builds on: `2026-09-30-problem-extractor-novelty-investigator-design.md`

## 1. Purpose and pipeline position

```
SourceScout → ProblemExtractor → [pick] NoveltyInvestigator → [pick] EconomicValueInvestigator
                                                                 → later: Personal fit → Opportunity generator
```

The Economic Value Investigator (EV) answers **"who cares, and is there money in it?"** for a problem,
with every amount traceable to evidence. Two parts:

- **`economicvalue score`** — free, deterministic, runs over *all* problems: the money and demand
  signals SourceScout already collected for each problem's sources.
- **`economicvalue assess <ids>`** — a web-searching agent on problems the user picks, answering the
  user's seven questions and producing estimates whose numbers are backed by cited, verified evidence.

### Success criteria

1. No dollar amount reaches a record without a basis: every amount lives in an estimate whose basis is
   a verified `source`, a verified `analogous_company`, or a labelled `explicit_assumption`; otherwise
   the value is `unknown`.
2. `potential_value` is computed by code from its factors, never produced by the model.
3. Free-text answers containing an amount that appears in no verified quote are flagged.
4. `assess` refuses problems NoveltyInvestigator marked `solved` (unless `--force`) and warns when no
   investigation exists.
5. Searches are counted from tool calls; `< min_searches` → `INSUFFICIENT SEARCH`.

## 2. Sources (what evidence the agent looks for)

1. **Money already committed** — award databases and funding pages (USAspending.gov, NIH RePORTER, NSF
   awards, EU CORDIS, funder programme pages), prizes, salary ranges; plus the payment signals the
   problem's own sources already carry.
2. **Market around the problem** — companies hiring for it, startups and products selling partial
   solutions, investment news; comparable companies (for `analogous_company` bases).
3. **Cost of the problem** — public statistics, SEC filings / earnings calls that quantify losses,
   industry and economic studies.

Deterministic award-database queries (USAspending/NIH/NSF APIs) are **out of v1**; added later as agent
tools only if measured coverage is poor.

## 3. Layout

```
EconomicValueInvestigator/
  config.yaml  economic_value_schema.yaml  README.md
  economicvalue/        config, money, score, schema, prompt, estimates, assess, cli
  tests/                ev_testing.py + test_ev_*.py (no conftest; prefixed names)
  assessments/<problem-id>.yaml     versioned output
  data/                 scores.yaml (derived), transcripts/ (git-ignored)
```

Shared code: `rqd` (agent mode, `YamlStore`, CLI helpers, locks, fetcher). The citation check
`verify_work` moves from `noveltyinvestigator/verify.py` to `rqd/verify.py`; NI imports it (one copy).
The agent-run scaffolding NI and EV share (run agent → save transcript on success and failure → append
history on re-run) moves to `rqd/investigation.py`, NI migrates onto it.

## 4. `economicvalue score` (free, all problems)

For every `ProblemExtractor/problems/*.yaml`:

- parse every `payment_signal.stated` of its sources into amounts (`rqd`-free module
  `economicvalue/money.py`): `$1.5M`, `Award ceiling: 250,000`, `£50m`, `nearly £50m`,
  `$212,000 — $339,000 USD` (range), `USD 17,000`, `€2 million`; amounts without a currency are kept
  with `currency: null` and excluded from USD totals;
- convert with **fixed, visible rates** from `config.yaml` (`currency_rates_usd`, dated); no network;
- components: `sources`, `distinct_source_ids`, `best_tier`, `payment_types`, `max_committed_usd`
  (largest award/prize/contract amount), `salary_range_usd`, `next_deadline`, `unparsed_amounts`.

Output: `data/scores.yaml` (derived, regenerated each run) and a table on stdout sorted by
`max_committed_usd`, then `sources`. No opaque combined score: components are shown side by side.

## 5. `economicvalue assess <problem-id> [...]` (paid, picked)

### 5.1 Gate
- NI investigation exists with `novelty.status: solved` → `RqdError` ("NoveltyInvestigator marked it
  solved"), unless `--force` (then recorded as `gate: forced`).
- No investigation → proceed, record `gate: not_investigated`, log a warning.

### 5.2 Agent
One `claude -p --safe-mode` session (`WebSearch`, `WebFetch`, `--max-budget-usd`, stream-json), model and
effort from config (`claude-opus-5-5`, `medium`), input = the PE problem record + the free score + NI's
closest work and counterargument if present. The system prompt:
- the seven questions: who has this problem, how frequently, how expensive, what they do currently,
  what failure costs, could a solution be deployed, who controls the budget;
- the three source families (§2); never answer from memory; ≥ `min_searches` searches;
- **amounts only in `estimates`**; each estimate row names its basis: `source` / `analogous_company`
  (with the number of an `evidence` entry whose quote contains the supporting text) or
  `explicit_assumption` (with the assumption stated); `unknown` (no row) is better than a guess.

### 5.3 Model-facing schema (flat)
Top-level scalars: `beneficiary_type`, `beneficiary_description`, `pain_score` (1–10), `pain_reasoning`,
`who_has_problem`, `how_frequently`, `how_expensive`, `current_practice`, `failure_consequence`,
`deployment` (`plausible|difficult|implausible|unknown`), `deployment_barriers`, `buyer`,
`urgency` (`low|medium|high|unknown`), `urgency_reasoning`, `confidence`.
Lists of flat objects:
- `evidence`: `title, url, kind (award|prize|statistic|filing|report|company|news|job_posting|paper|other),
  company, quote`;
- `estimates`: `quantity (affected_units|frequency_per_year|cost_per_occurrence|addressable_share|
  current_cost|failure_cost), low, high, unit, basis (source|analogous_company|explicit_assumption),
  evidence (1-based, 0 for assumptions), assumption`;
- `willingness_to_pay`: `signal, evidence` (committed money found, e.g. an award).

### 5.4 Code-side rules (estimates.py)
1. Every `evidence` entry is fetched and quote-checked (`rqd.verify`) → `verified|quote_not_found|unfetchable`.
2. Estimate rows are grouped by `quantity`. A basis row is **valid** if `source`/`analogous_company` →
   its evidence number exists and is `verified`; `explicit_assumption` → non-empty `assumption`.
3. Status per quantity: `supported` (≥ 1 valid cited basis) · `assumption_only` (only valid assumptions)
   · otherwise the value becomes `unknown` and the rejected rows are listed in `warnings`.
   `low`/`high` of the quantity = min/max over its valid rows.
4. Units: `cost_per_occurrence`, `current_cost`, `failure_cost` must be in `USD` (or a unit listed in
   `currency_rates_usd`, converted by code); otherwise `unknown` + warning. `addressable_share` in [0, 1].
5. `potential_value` (USD/year) = affected_units × frequency_per_year × cost_per_occurrence ×
   addressable_share, computed by code from low and from high; `unknown` if any factor is unknown;
   status = weakest factor status; basis = union of factor bases.
6. Amount guard: every currency amount found in the free-text answers must appear in some verified
   evidence quote; otherwise it is listed in `warnings.unsupported_amounts`.
7. `willingness_to_pay` entries keep only those whose evidence is verified; the rest go to warnings.

### 5.5 Record `assessments/<problem-id>.yaml` (user format)
```yaml
problem_id: prob-…
revision: 1
gate: passed | not_investigated | forced
economic_value:
  beneficiary: {type: AI_startup, description: ...}
  pain: {score: 8, reasoning: ...}
  current_cost: <estimate> | unknown
  failure_cost: <estimate> | unknown
  potential_value: <estimate> | unknown          # computed by code
  buyer: CTO / Head_of_Research
  deployment: {assessment: plausible, barriers: ...}
  urgency: {level: medium, reasoning: ...}
  willingness_to_pay: [{signal: ..., evidence: 2}]
questions: {who_has_problem, how_frequently, how_expensive, current_practice, failure_consequence,
            deployment, buyer}
factors: {affected_units: <estimate>|unknown, frequency_per_year: ..., cost_per_occurrence: ..., addressable_share: ...}
evidence: [{title, url, kind, company, quote, verification}]
warnings: {rejected_estimates: [...], unsupported_amounts: [...], unverified_wtp: [...]}
search: {searches, fetches, queries, sufficient}
confidence: 0.6
assessed_with: {model, effort, answered_by, cost_usd_equivalent, output_tokens, input_tokens, turns,
                duration_s, at, transcript}
history: []
```
`<estimate>` = `{low, high, unit, status: supported|assumption_only, basis: [{type: source, url, quote,
verification} | {type: analogous_company, company, url, quote, verification} | {type:
explicit_assumption, assumption}]}`.

### 5.6 Commands
```
uv run economicvalue score
uv run economicvalue assess <problem-id> [...] [--force]
uv run economicvalue list        # potential_value, statuses, pain, urgency, warnings count
uv run economicvalue show <problem-id>
```

## 6. Mapping to `research_opportunity_schema.yaml`
`economic_value.beneficiary` ← `beneficiary`; `estimated_value` ← `potential_value`; `urgency` ←
`urgency.level`; `willingness_to_pay` ← `willingness_to_pay` (+ score's committed money).

## 7. Testing
Money parsing table; score over fixture problems; estimate status rules (each rule has a test);
potential_value arithmetic and unknown propagation; unit rejection; amount guard; gate; agent path with
recorded stream-json (as NI); CLI; one live test on a real problem asserting no unsupported amounts reach
`economic_value`.
