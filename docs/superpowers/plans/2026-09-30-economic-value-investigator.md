# Economic Value Investigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build `EconomicValueInvestigator/` (`economicvalue score | assess | list | show`) so every economic claim about a problem is either backed by verified evidence, a labelled assumption, or `unknown`.

**Architecture:** Free deterministic score over all ProblemExtractor records (money parsing of stored payment signals, fixed currency rates). Paid assessment = one `claude -p` agent session per picked problem (reusing `rqd` agent mode), followed by code-side verification and estimate rules; `potential_value` computed by code. Shared agent-run scaffolding and citation verification move to `rqd` and NoveltyInvestigator migrates onto them.

**Tech Stack:** Python 3.12, uv, pydantic v2, typer, httpx, selectolax, pypdf, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-economic-value-investigator-design.md`

## Global Constraints
- `uv run` for everything; atomic commits; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No duplication: `verify_work` → `rqd/verify.py`; agent-run scaffolding → `rqd/investigation.py`; NI migrates in the same task (its tests unchanged except imports).
- Model-facing schema flat (lists of flat objects only); verification, statuses, search counts and `potential_value` are derived by code, never model output.
- No amount without a basis (spec §5.4); `unknown` is a first-class value.
- Tests: `EconomicValueInvestigator/tests/` has no conftest; files `test_ev_*.py`, helper `ev_testing.py`.

## Review Focus
1. An estimate citing an evidence number that does not exist or whose quote fails → rejected, value `unknown` if no other valid basis, listed in warnings.
2. A free-text answer containing "$40M" that appears in no verified quote → `warnings.unsupported_amounts`.
3. One factor unknown → `potential_value: unknown`; all factors assumption-only → potential_value `assumption_only`.
4. A cost estimate in "EUR" converts with configured rate; in "person-hours" → unknown + warning.
5. `assess` on an NI-`solved` problem refuses without `--force`; budget/timeout errors → no file, next id continues (shared scaffolding).

---

### Task 1: Shared verification and agent-run scaffolding in `rqd`; NI migrates
- Move `NoveltyInvestigator/noveltyinvestigator/verify.py::verify_work` → `common/rqd/verify.py` (same body); NI imports it; NI verify tests → `common/tests/test_rqd_verify.py` (pdf helper moves to `rqd_testing.py`).
- `common/rqd/investigation.py`: `run_agent_logged(client, *, transcripts_dir, record_id, run_id, **agent_kwargs) -> tuple[AgentResult, str]` (saves transcript on success and on `AgentError` then re-raises); `search_summary(tool_calls, min_searches) -> dict` (searches, fetches, queries, sufficient); `with_history(store, record_id, record, keep: tuple[str, ...]) -> dict` (revision + history).
- NI `investigate_one` uses the three helpers; all NI tests pass unchanged except imports.
- [ ] Tests first for the three helpers (`test_rqd_investigation.py`); then move; full suite green; commit `refactor(rqd): shared verification and agent-run scaffolding`.

### Task 2: Money parsing and the free score
- `economicvalue/money.py`: `Money(low: float, high: float, currency: str | None, text: str)`; `parse_amounts(text) -> list[Money]` (symbols $ £ €, codes USD/GBP/EUR, suffixes k/m/million/bn/billion, thousands separators, ranges with — – - "to"); `to_usd(m, rates) -> tuple[float, float] | None`.
- `economicvalue/config.py`: `EVConfig(agent: AgentCfg, http: HttpCfg, problemextractor_root, noveltyinvestigator_root, currency_rates_usd: dict[str, float])` — `AgentCfg` reused from `rqd` (move NI's `AgentCfg` to `rqd/config.py`; NI imports it).
- `economicvalue/score.py`: `score_problem(record, rates) -> dict` (spec §4 components); `score_all(problems_store, rates) -> list[dict]`.
- [ ] Tests `test_ev_money.py` (table of the spec's examples + no-currency + garbage), `test_ev_score.py` (fixture problem with grant/prize/salary sources → components; unparsed amounts listed).
- [ ] Implement; commit `feat(ev): money parsing and free own-data score`.

### Task 3: Schema, prompt, estimate rules
- `economicvalue/schema.py`: flat `EVOutput` (spec §5.3) + `EV_SCHEMA = api_schema(EVOutput)`; test the schema is flat.
- `economicvalue/prompt.py`: system prompt (seven questions, three source families, amounts only in estimates, basis rules, unknown over guessing, ≥ min_searches); `render_input(problem, score, investigation | None)`.
- `economicvalue/estimates.py`: `build(out, evidence_verification: list[str], rates) -> dict` returning `factors`, `current_cost`, `failure_cost`, `potential_value`, `willingness_to_pay`, `warnings` per spec §5.4 rules 2–7.
- [ ] Tests `test_ev_estimates.py`: one test per rule (valid source; invalid evidence number; unverified quote; assumption-only; mixed → supported with min/max; unit EUR converted; unit person-hours rejected; share > 1 rejected; potential product low/high; unknown propagation; weakest status; amount guard hit and miss; WTP unverified dropped).
- [ ] Implement; commit `feat(ev): flat schema, prompt and evidence-backed estimate rules`.

### Task 4: `assess` command, records, CLI, docs
- `economicvalue/assess.py`: gate (spec §5.1); `run_agent_logged`; validate `EVOutput`; verify evidence (`rqd.verify`); `estimates.build`; record (spec §5.5) incl. `gate`, `search_summary`, `assessed_with.answered_by`; `with_history`; multi-id loop like NI (`AgentError` per id; `ExtractionConfigError` stops).
- `economicvalue/cli.py`: `score`, `assess <ids> [--force]` (exit 1 if any failed), `list`, `show`; `@exclusive` on `assess`; pyproject script `economicvalue`; package/testpaths; `.gitignore` `EconomicValueInvestigator/data/`.
- `README.md`, `economic_value_schema.yaml`, root README pipeline row.
- [ ] Tests `test_ev_assess.py` (recorded stream-json + mocked HTTP: record fields; potential_value computed; warnings; gate refuse/force/not_investigated; budget error continues; usage limit stops), `test_ev_cli.py`.
- [ ] Implement; commit `feat(ev): assess command with verified, basis-backed estimates`.

### Task 5: Live verification, review, PR
- [ ] Live test (`-m live`): assess one real problem from a copy of the live data; assert every amount in `economic_value` has status `supported`/`assumption_only` or is `unknown`, and `warnings` is present.
- [ ] Real run on 2 picked problems (e.g. the ARIA and a grants.gov problem); inspect estimates/bases; record cost/time.
- [ ] Fresh whole-branch review (most capable model); fix Critical/Important test-first; PR.
