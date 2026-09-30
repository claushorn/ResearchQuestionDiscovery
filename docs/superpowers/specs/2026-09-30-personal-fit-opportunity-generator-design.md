# Personal-Fit Investigator + Opportunity Generator — Design Spec

Date: 2026-09-30
Status: approved in conversation; written for review
Builds on: the ProblemExtractor, NoveltyInvestigator and EconomicValueInvestigator specs (same date)

## 1. Purpose and pipeline position

```
SourceScout → ProblemExtractor → (optional) NoveltyInvestigator → (optional) EconomicValueInvestigator
                              └→ PersonalFitInvestigator → OpportunityGenerator → research brief
```

- **PersonalFitInvestigator (PF)** answers, per problem: *"If the person with this profile attacked this problem
  tomorrow, what advantage would they have over a random strong ML researcher?"* Every claimed advantage must rest
  on a verbatim quote from the user's own profile files.
- **OpportunityGenerator (OG)** combines what is known — technical novelty, economic value, tractability, personal
  advantage — into an **opportunity profile** (not a 1-D score), a short thesis ("why this could be worth spending
  10 hours investigating") and a **one-page research brief**. It is the first stage allowed to say **INVESTIGATE**.

Decisions from the conversation:
- The profile is evidence the user writes, in `personal_profile/` (git-ignored: the repository is public).
  Self-ratings alone cannot establish an advantage over a strong ML researcher.
- Novelty and economic value are **optional** inputs: when their stage has not run, the dimension is `unknown`
  and the brief says so. Nothing is filled in by assumption. PF is required for OG.
- Each stage consumes, never re-derives, what an earlier stage produced (single source of truth).
- Out of scope: finished challenges (ChallengeInvestigator) as opportunities; running earlier stages
  automatically.

## 2. Profile: `personal_profile/` (git-ignored)

A directory of free-form files, all read as evidence (`.md`, `.txt`, `.yaml`, `.yml`, `.pdf`; PDF text via
`rqd.http.pdf_to_text`). As of 2026-09-30 it holds:
- CV versions for different audiences (PDF);
- a text snapshot of the user's website (the live site is a JavaScript app, so its text is snapshotted from the
  site's source rather than fetched at run time);
- a list of the user's public repositories;
- summaries of private projects the user built;
- a file of facts the user stated that are in no CV;
- `capabilities.yaml` (self-ratings) and `interests.yml`, moved from the repository root (tracked copies removed;
  they remain in git history).

`.gitignore` gets `personal_profile/` (the repository is public). The expected contents are described in
`PersonalFitInvestigator/README.md`. Snapshots and summaries are refreshed on request, not by the tools.

Loading (`personalfit.profile`): every supported file, sorted by path, as `{path, text}`; a missing or empty
directory, an unsupported file type, or a total above `profile_max_chars` (config, default 200 000) is a clean
`ConfigError` with the fix. `profile_digest` = SHA-256 over the paths and texts, recorded on every fit so a
changed profile marks fits stale. Several CV versions repeat facts; that is harmless (any file may be cited).

## 3. PersonalFitInvestigator

Package `PersonalFitInvestigator/` (`personalfit`), CLI `fit`:
```
uv run fit assess <problem_id> [...]   # one agent call per problem
uv run fit list                        # advantage score, #advantages, stale?, problem statement
uv run fit show <problem_id>
```
**Input to the agent:** the problem record (ProblemExtractor), the Novelty investigation and EV assessment if they
exist (read-only, via their `YamlStore`s), and all profile files. **One call, no web tools** (the comparison is
profile vs problem; cost ≈ $0.1–0.3), effort medium, `max_budget_usd` 0.5.

**Model output (flat):**
- `advantages[]`: `claim`, `file` (profile path), `quote` (verbatim from that file), `why_ml_researcher_lacks_it`
- `gaps[]`: `gap`, `how_to_close`
- `interest_match`: high | medium | low | none, `interest_quote` (verbatim from a profile file, empty for none)
- `personal_advantage`: integer 0–10, `reasoning`, `confidence` 0–1

**Code rules:**
- Each advantage quote must be found in the named profile file (`rqd.quotes.quote_in_text`, ≥ 3 words);
  otherwise the advantage is dropped with a warning. Same for `interest_quote` (else `interest_match` → `none` + warning).
- An advantage whose file is `capabilities.yaml` is a **self-rating** (`basis: self_rating`). If no kept advantage
  rests on another file, `personal_advantage` is capped at `self_rating_cap` (config, default 5) with a warning —
  a self-rating cannot distinguish the user from a strong ML researcher.
- If no advantage survives, `personal_advantage` is capped at `no_advantage_cap` (default 2) with a warning.

**Record** `PersonalFitInvestigator/fits/<problem_id>.yaml`: `problem_id`, `problem_revision`,
`profile_digest`, `advantages` (kept, each with `basis: profile | self_rating`), `gaps`, `interest_match`,
`personal_advantage {score, stated_by_model, reasoning, confidence}`, `warnings`, `run {model, effort, cost, …,
transcript}`, `history` (earlier revisions). `list` marks a fit **stale** when the problem revision or the profile
digest changed.

## 4. OpportunityGenerator

Package `OpportunityGenerator/` (`opportunitygenerator`), CLI `opportunities`:
```
uv run opportunities generate <problem_id> [...]   # requires a fit; novelty / EV optional
uv run opportunities list                          # OPP id, recommendation, profile, title question
uv run opportunities show <OPP-id | problem_id>    # the record; `--brief` prints the brief
```
**Input to the agent:** problem, fit, Novelty investigation (optional), EV assessment (optional). Agent session
with WebSearch/WebFetch (`min_searches` 2: data, benchmarks, compute needed for a first experiment), effort
medium, `max_budget_usd` 1.0.

**Copied from earlier stages (never re-rated):**
- personal advantage score + confidence + kept advantages (PF);
- novelty status, confidence, strongest counterargument, closest work (Novelty) — or `unknown`;
- beneficiary, buyer, potential value range, confidence (EV) — or `unknown`.

**Model output (flat):** `title_question` ("Can X be learned despite Y?"); `novelty_score` (0–10 or null) +
`novelty_reasoning`; `economic_value_score` (0–10 or null) + `value_reasoning`; `tractability_score` (0–10),
`tractability_reasoning`, `tractability_confidence`; `asymmetric_upside` low | medium | high + reasoning;
`engagement_consulting | _research | _startup | _employment` (high | medium | low); `why_unsolved`;
`current_best_approach`; `what_we_could_test`; `first_experiment` + `first_experiment_hours` +
`first_experiment_compute_usd` (labelled assumptions); `if_successful`; `if_failed`; `thesis` (why this could be
worth 10 hours); `next_step` investigate | contact + `next_step_reason`; `evidence[]` (verbatim quotes, verified
by code as in the other stages).

**Code rules:**
- `novelty_score` must be null exactly when Novelty is missing or its status is `unclear`; with status `solved`
  it must be ≤ 3, `partially_solved` ≤ 7. `economic_value_score` must be null exactly when EV is missing.
  A violation is a rejected output (`AgentError`, item fails, transcript kept) — no silent correction.
- `personal_advantage` in the profile is the fit's (capped) score, never the model's.
- Decimals and percentages in the text fields that no verified quote or upstream record states →
  `warnings.unsupported_numbers` (the CI / EV guard, shared helper). The experiment's hours and $ are labelled
  assumptions and exempt.
- **Recommendation (code, config thresholds):** `ignore` unless personal advantage ≥ 7, tractability ≥ 5,
  novelty (if known) ≥ 5, economic value (if known) ≥ 4, and novelty status ≠ `solved`. Otherwise the model's
  `next_step` decides `investigate` or `contact`. The model cannot override `ignore`.
- Staleness: the record keeps the revisions/digests of every input; `list` marks it stale when an input changed.

**OPP ids:** `OPP-0001`, `OPP-0002`, … assigned on first generation, stable per problem (a re-run keeps the id and
adds history).

**Record** `OpportunityGenerator/opportunities/OPP-NNNN.yaml`, extending the existing draft
`opportunities/research_opportunity_schema.yaml` (moved to `OpportunityGenerator/opportunity_schema.yaml`, the
draft removed):
```yaml
id: OPP-0042
problem_id: prob-…
title: "Can X be learned despite Y?"
opportunity_profile:
  novelty: 8            # /10 or unknown
  economic_value: 7     # /10 or unknown
  tractability: 5
  personal_advantage: 9 # from the fit
  asymmetric_upside: high
  likely_engagement: {consulting: high, research: high, startup: medium, employment: low}
confidence: {novelty: 0.71, value: 0.63, tractability: 0.58, fit: 0.91}   # each stage's own confidence
thesis: ...
recommendation: investigate | contact | ignore
recommendation_reason: ...
brief_sections: {...}   # the texts rendered into the brief
inputs: {problem_revision, fit_profile_digest, novelty_revision | null, ev_revision | null}
evidence: [...]
warnings: {...}
run: {...}
history: []
```

**Research brief** `OpportunityGenerator/briefs/OPP-NNNN.md`, rendered by code from the record:

```
==========================================================
OPP-0042
CAN X BE LEARNED DESPITE Y?
==========================================================
PROBLEM                  problem.precise_statement (ProblemExtractor)
WHY THIS MAY BE UNSOLVED model text (+ novelty status, or "novelty not checked")
CURRENT BEST APPROACH    model text
STRONGEST COUNTEREVIDENCE Novelty strongest_counterargument, verbatim — or "not checked: run noveltyinvestigator"
ECONOMIC BENEFICIARY     EV beneficiary, buyer, potential value range — or "not assessed: run economicvalue"
WHY CLAUS?               the fit's kept advantages (with their profile file)
WHAT WE COULD TEST       model text
ESTIMATED FIRST EXPERIMENT  ~H hours, ~$C compute (assumptions)
IF SUCCESSFUL / IF FAILED   model text
CONFIDENCE               Novelty / Value / Tractability / Fit (— when unknown)
OPPORTUNITY PROFILE      scores /10, asymmetric upside, likely engagement
THESIS                   model text
RECOMMENDATION           [ ] Ignore  [x] Investigate  [ ] Contact someone
==========================================================
```
The name in "WHY CLAUS?" comes from config (`profile_name`).

## 4b. Revisions after the final review (2026-10-01)

- Fit records, opportunity records and briefs quote the private profile verbatim: their directories are
  git-ignored (only `.gitkeep` tracked).
- OG checks every input before spend: stale fit (problem revision changed), unknown novelty status, malformed
  upstream records and stray files in `opportunities/` are `RqdError`s with a fix.
- Interest quotes verify as whole lines of a profile file (any length); advantages keep the ≥ 3-word quote rule.
- Numbers are backed only by verified quotes and the problem's stated (not `*_inferred`) fields, never by an
  earlier stage's prose (e.g. Novelty's counterargument).

## 5. Shared code

- The unsupported-numbers guard used by ChallengeInvestigator moves to `rqd` (one helper) and is used by OG.
- Reading upstream records uses `rqd.records.YamlStore` on the other stages' directories (paths in config), as
  EconomicValueInvestigator reads Novelty investigations.
- Agent sessions: `rqd.investigation.run_agent_logged`, `run_each`; evidence: `rqd.verify.verify_work`.

## 6. Errors

Deterministic problems (unknown problem id, missing fit for OG, profile missing/too large, bad config) →
`RqdError`/`ConfigError` with a fix, printed cleanly by the CLI. An agent failure or a rejected output fails that
item only (`AgentError`), the rest of the run continues; transcripts are kept.

## 7. Testing

Fake runner / fake fetcher as in the other packages; test-first for every code rule: quote verification against
profile files, self-rating and no-advantage caps, stale detection, novelty/value null rules and bands,
recommendation thresholds (each boundary), OPP id stability, brief rendering with and without Novelty/EV, CLI end
to end, and one `-m live` test per stage.

## 8. Cost

PF ≈ $0.1–0.3 per problem (no web); OG ≈ $0.3–1.0 per problem (list-price equivalent on the subscription).
