# Personal-Fit Investigator + Opportunity Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new pipeline stages — `fit` (personal advantage over a strong ML researcher, backed by verbatim profile
quotes) and `opportunities` (opportunity profile, thesis, code-decided recommendation, one-page research brief).

**Architecture:** Two packages mirroring EconomicValueInvestigator: config.py / schema.py (flat model output) /
prompt.py / a rules module (pure functions, all code-side checks) / run.py (context, one agent session per item,
`run_each`) / cli.py (typer). Earlier stages' records are read with `rqd.records.YamlStore`, copied, never re-derived.

**Tech Stack:** Python 3.12, pydantic, typer, pyyaml, `claude -p` via `rqd.claude_code`, pytest with FakeRunner/make_fetcher.

**Spec:** `docs/superpowers/specs/2026-09-30-personal-fit-opportunity-generator-design.md`

## Global Constraints

- `personal_profile/` is git-ignored as a whole; no profile content in tests or fixtures (use tmp dirs).
- No invented numbers: advantages need verified profile quotes; novelty/value scores null when their stage is missing.
- The model cannot override `ignore`; a rule violation in model output is an `AgentError` (item fails, transcript kept).
- Consume, never re-derive: fit score in OG comes from the fit record; counterargument / beneficiary from NI / EV.
- Deliberate failures are `RqdError`/`ConfigError` with a `fix`; CLI prints them cleanly (`rqd.cli.clean_errors`).
- Delete superseded code in the same change: root `capabilities.yaml`, `interests.yml`,
  `opportunities/research_opportunity_schema.yaml` (moved), CI's private unsupported-numbers loop (moved to rqd).
- Tests prefixed per package (`test_pf_*.py`, `test_og_*.py`) with helper modules `pf_testing.py`, `og_testing.py`.
- `uv run` for everything; atomic commits.

## Review Focus

1. A profile quote that exists only in a *different* profile file than the one cited — must not verify.
2. An advantage citing `capabilities.yaml` plus one citing a CV: no self-rating cap (the CV one carries it).
3. NI present with status `unclear` → novelty must be null; NI `solved` → recommendation ignore even if all scores high.
4. Re-generating an opportunity keeps its OPP id; two new problems get distinct consecutive ids.
5. The brief renders when NI and EV are both missing (explicit "not checked"/"not assessed" lines, no `None`).

---

### Task 1: Shared unsupported-numbers guard

**Files:** Modify `common/rqd/numbers.py`, `ChallengeInvestigator/challengeinvestigator/run.py`; Test `common/tests/test_rqd_numbers.py`.

**Interfaces — Produces:** `rqd.numbers.unsupported_numbers(texts: list[tuple[str, str]], quotes: list[str],
backed: list[float]) -> list[str]` — for every decimal/percentage in each named text (`numbers_in_text`) that no
quote states (`stated`, or for a percentage the fraction via `figure_in_quote(v/100, q, "%")`) and that equals no
`backed` value (`same_number`): `"<name>: <value:g>[%]"`.

- [ ] Test: `unsupported_numbers([("summary", "gains 12.5% over 0.9, ceiling 1.0")], ["scored 0.9 overall"], [1.0]) == ["summary: 12.5%"]`.
- [ ] Run → FAIL (ImportError). Implement. Run → PASS.
- [ ] Migrate CI `investigate_one` to it; delete `_supported_number`. Full suite green. Commit.

### Task 2: PersonalFitInvestigator

**Files:** Create `PersonalFitInvestigator/{README.md,config.yaml,fit_schema.yaml,fits/.gitkeep}`,
`PersonalFitInvestigator/personalfit/{__init__,config,profile,schema,prompt,rules,run,cli}.py`,
`PersonalFitInvestigator/tests/{pf_testing.py,test_pf_profile.py,test_pf_rules.py,test_pf_run.py,test_pf_live.py}`.
Modify `pyproject.toml` (script `fit`, package, testpath), `.gitignore` (`personal_profile/`,
`PersonalFitInvestigator/data/`), delete root `capabilities.yaml`, `interests.yml`.

**Interfaces — Produces:**
- `PFConfig(agent: AgentCfg, profile_dir: str, profile_max_chars: int, self_rating_files: list[str],
  self_rating_cap: int, no_advantage_cap: int, problemextractor_root, noveltyinvestigator_root, economicvalue_root)`.
- `profile.load_profile(directory: Path, max_chars: int) -> Profile(files: list[ProfileFile(path: str, text: str)], digest: str)`;
  `profile.render(profile) -> str` (each file as `<file path="...">…</file>`).
- `schema.FitOutput`: `advantages: list[Advantage(claim, file, quote, why_ml_researcher_lacks_it)]`,
  `gaps: list[Gap(gap, how_to_close)]`, `interest_match: high|medium|low|none`, `interest_quote: str = ""`,
  `personal_advantage: int (0..10)`, `reasoning: str`, `confidence: float (0..1)`; `FIT_SCHEMA`.
- `rules.apply(out: FitOutput, profile: Profile, cfg: PFConfig) -> dict` with keys `advantages` (kept, each +
  `basis: profile|self_rating`), `gaps`, `interest_match {level, quote}`, `personal_advantage {score,
  stated_by_model, reasoning, confidence}`, `warnings: list[str]`.
- `run.PFContext.open(paths, cfg, client)`, `run.assess(ctx, problem_ids) -> dict[str, str]` (failures),
  `run.is_stale(fit, problem, profile) -> bool`. Record `fits/<problem_id>.yaml`: `problem_id, revision,
  problem_revision, profile_digest, advantages, gaps, interest_match, personal_advantage, warnings, run, history`.
- CLI `fit assess <ids>`, `fit list`, `fit show <id>`.

**Tests (write first, watch fail):**
- profile: loads md/txt/yaml/pdf sorted; digest changes when a file changes; missing dir / empty dir / unsupported
  file / too large → `ConfigError` with fix.
- rules: quote found in cited file → kept; quote only in another file → dropped + warning (Review Focus 1); fewer
  than 3 words → dropped; unknown file → dropped; only self-rating advantages → score capped at 5 + warning;
  self-rating + CV advantage → not capped (Review Focus 2); none kept → capped at 2; model score below cap
  unchanged; interest quote unverified → level `none` + warning.
- run: prompt contains profile + problem + NI/EV when present; no tools passed; record written with digest and
  problem revision; unknown problem id → RqdError before any spend; AgentError on one problem, others continue;
  stale when profile or problem revision changes; CLI assess/list/show end to end.
- live (`-m live`): one real fit on a fixture problem with a tmp profile dir.

- [ ] Steps: tests → FAIL → implement → PASS per module; full suite; commit.

### Task 3: OpportunityGenerator

**Files:** Create `OpportunityGenerator/{README.md,config.yaml,opportunities/.gitkeep,briefs/.gitkeep}`,
`OpportunityGenerator/opportunity_schema.yaml` (moved from `opportunities/research_opportunity_schema.yaml`, rewritten
to the spec's record), `OpportunityGenerator/opportunitygenerator/{__init__,config,schema,prompt,rules,brief,ids,run,cli}.py`,
tests `OpportunityGenerator/tests/{og_testing.py,test_og_rules.py,test_og_brief.py,test_og_ids.py,test_og_run.py,test_og_live.py}`.
Modify `pyproject.toml` (script `opportunities`), `.gitignore` (`OpportunityGenerator/data/`), root `README.md`
(pipeline table rows for fit and opportunities).

**Interfaces — Consumes:** Task 2's fit record; NI `novelty {status}`, `confidence`, `strongest_counterargument`,
`revision`; EV `economic_value {beneficiary, buyer, potential_value}`, `confidence`, `revision`; PE
`problem.precise_statement`, `revision`. Task 1's `unsupported_numbers`.

**Interfaces — Produces:**
- `OGConfig(agent, profile_name: str, thresholds: Thresholds(fit: int, tractability: int, novelty: int, value: int),
  http, problemextractor_root, noveltyinvestigator_root, economicvalue_root, personalfit_root)`.
- `schema.OGOutput` (flat, spec §4 fields) + `evidence: list[Evidence(title,url,quote)]`; `OG_SCHEMA`.
- `rules.check(out, novelty: dict|None, ev: dict|None) -> None` (raises `ValueError` naming the rule);
  `rules.recommend(profile: dict, novelty_status: str|None, next_step: str, thresholds) -> tuple[str, str]`.
- `ids.opp_id_for(store: YamlStore, problem_id) -> str` (existing id, else next `OPP-NNNN`).
- `brief.render(record: dict, problem: dict, fit: dict, novelty: dict|None, ev: dict|None, profile_name: str) -> str`.
- `run.generate(ctx, problem_ids) -> dict[str, str]`; record `opportunities/OPP-NNNN.yaml`, brief `briefs/OPP-NNNN.md`.
- CLI `opportunities generate <ids>`, `list`, `show <OPP-id|problem_id> [--brief]`.

**Tests (write first, watch fail):**
- rules.check: novelty null iff NI missing or `unclear` (both directions); `solved` → ≤ 3, `partially_solved` ≤ 7;
  value null iff EV missing.
- rules.recommend: each threshold boundary (fit 7 vs 6, tractability 5 vs 4, novelty 5 vs 4, value 4 vs 3);
  unknown novelty/value do not block; `solved` → ignore (Review Focus 3); eligible → model's investigate/contact.
- ids: first `OPP-0001`, second problem `OPP-0002`, re-run keeps id (Review Focus 4).
- brief: all sections in order; NI/EV missing → "not checked: run noveltyinvestigator" / "not assessed: run
  economicvalue", no "None" (Review Focus 5); advantages listed with profile file; checkboxes mark the recommendation;
  confidence line uses each stage's confidence, "—" when unknown.
- run: missing fit → RqdError before spend; personal_advantage copied from fit (model cannot change it); rule
  violation → item fails with AgentError, others continue; evidence verified; unsupported numbers warned
  (experiment hours/$ exempt); record + brief written; stale inputs listed; CLI end to end.
- live: one real generation on fixture records.

- [ ] Steps: tests → FAIL → implement → PASS per module; full suite; commit.

### Task 4: Live check, docs, final review

- [ ] `uv run pytest -m live` for the two new live tests.
- [ ] Real run on the user's data: `fit assess` + `opportunities generate` for 2 problems with the real
  `personal_profile/`; inspect the brief.
- [ ] Final whole-branch review (fresh reviewer, most capable model); fix Critical/Important test-first; PR.
