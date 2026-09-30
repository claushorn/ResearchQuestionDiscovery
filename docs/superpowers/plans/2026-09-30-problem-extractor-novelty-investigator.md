# Problem Extractor & Novelty Investigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Extract shared code into `common/rqd`, then build the Problem Extractor (merged, document-only problem records) and the adversarial Novelty Investigator (user-picked problems, web-searching Claude Code agent, verified evidence).

**Architecture:** One uv project with packages `rqd` (shared), `sourcescout`, `problemextractor`, `noveltyinvestigator`; one CLI per capability; each capability in its own directory. LLM calls go through `rqd.claude_code` (`claude -p --safe-mode`, subscription billing). PE is one structured call per candidate with a TF-IDF shortlist for merging; NI is one agent session per problem (`WebSearch`, `WebFetch`, `stream-json`), followed by deterministic quote verification of every cited work.

**Tech Stack:** Python 3.12, uv, pydantic v2, typer, httpx, selectolax, pypdf (new, NI PDF verification), pytest. No new ML dependency: TF-IDF is ~30 lines of pure Python.

**Spec:** `docs/superpowers/specs/2026-09-30-problem-extractor-novelty-investigator-design.md`

## Global Constraints

- `uv run` for everything; commits atomic (`git add … && git commit …` in one call), trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The refactor is a pure move: SourceScout behaviour and its 94 tests unchanged except import paths. `ScoutError` is renamed `RqdError` everywhere; no alias.
- No duplication: anything two capabilities need lives in `rqd` (quote verification, fetcher, claude client, CLI helpers, YAML/config helpers, errors, time).
- Every quote is verified by code; the model never supplies verification status, search counts or URLs that code can derive.
- `"not stated"` instead of invention (PE); `min_searches` enforced from counted tool calls (NI).
- API-key variables stripped from every `claude` subprocess.
- Test layout: new test dirs have **no** `conftest.py` and **prefixed** file names (`test_rqd_*.py`, `test_pe_*.py`, `test_ni_*.py`) plus uniquely named helper modules, because pytest's default import mode collides on repeated `conftest`/basenames.

## Review Focus

1. A candidate whose model output names a `merge_with` id outside the shortlist → treated as new problem and reported, never merged silently.
2. Re-running `problemextractor run` → processes 0 candidates (state DB), even after SourceScout re-extracts an item (new revision = new candidate id → processed once).
3. NI model cites a URL that 404s / is a PDF / quotes a search snippet → `unfetchable` / PDF text checked / `quote_not_found`; investigation still written.
4. NI session hits `--max-budget-usd` or an error mid-run → no investigation file, error reported, remaining problems continue; usage limit → clean stop.
5. NI answers from memory (0 searches) → `search.sufficient: false`, `list` shows `INSUFFICIENT SEARCH`.

## File Structure

```
pyproject.toml                         MODIFY: packages rqd/problemextractor/noveltyinvestigator, scripts, testpaths, pypdf
common/rqd/{__init__,errors,config,timeutil,http,quotes,claude_code,cli}.py   CREATE (moved code)
common/tests/test_rqd_{http,quotes,claude_code}.py + rqd_testing.py            CREATE (moved tests + agent tests)
SourceScout/sourcescout/…              MODIFY imports; DELETE http.py, timeutil.py, claude_code.py; errors.py keeps RegistryError only
ProblemExtractor/{config.yaml,problem_schema.yaml,README.md}
ProblemExtractor/problemextractor/{__init__,config,schema,similarity,state,records,extract,cli}.py
ProblemExtractor/tests/{pe_testing.py,test_pe_*.py}
NoveltyInvestigator/{config.yaml,novelty_schema.yaml,README.md}
NoveltyInvestigator/noveltyinvestigator/{__init__,config,schema,prompt,verify,records,investigate,cli}.py
NoveltyInvestigator/tests/{ni_testing.py,test_ni_*.py}
```

---

### Task 1: Move shared code into `common/rqd`

**Moves (content unchanged except imports):**
- `sourcescout/errors.py` → `rqd/errors.py`: `RqdError` (was `ScoutError`), `ConfigError`, `ExtractionConfigError`, `ItemExtractionError`, `SourceFetchError`. `sourcescout/errors.py` keeps only `class RegistryError(RqdError)`.
- `sourcescout/config.py`: `Strict`, `load_yaml`, `HttpCfg` → `rqd/config.py`; SourceScout config imports them.
- `sourcescout/timeutil.py` → `rqd/timeutil.py`; `sourcescout/http.py` → `rqd/http.py`; `sourcescout/claude_code.py` → `rqd/claude_code.py`.
- `quote_in_text` (+ `_QUOTES`, `_norm`) from `sourcescout/extract.py` → `rqd/quotes.py`.
- `make_client(cfg)` → `rqd/claude_code.py::make_client(backend: str)`; SourceScout calls `make_client(cfg.backend)`.
- CLI helpers from `sourcescout/cli.py` → `rqd/cli.py`: `clean_errors`, `exclusive` (lock at `<root>/data/run.lock`, message "another command is running on this directory"), `progress_to_stderr(logger_name)`, `load_repo_env(root)` (dotenv from `root.parent/.env`).
- Tests: `test_http.py` → `common/tests/test_rqd_http.py`; `quote_in_text` test → `test_rqd_quotes.py`; `test_claude_code.py` stays in SourceScout (it tests the extraction path) but imports `rqd.claude_code`. `make_fetcher` moves to `common/tests/rqd_testing.py`; SourceScout's conftest re-exports it (`from rqd_testing import make_fetcher`) — rootdir `pythonpath` includes `common/tests`.

**pyproject:** `packages = ["common/rqd", "SourceScout/sourcescout"]`; `testpaths = ["common/tests", "SourceScout/tests"]`; `pythonpath = ["common/tests"]` in pytest options.

- [ ] Step 1: `git grep -n "sourcescout.errors\|sourcescout.http\|sourcescout.timeutil\|sourcescout.claude_code\|ScoutError\|quote_in_text\|make_client"` → list every site.
- [ ] Step 2: move files with `git mv`, rewrite imports, rename `ScoutError` → `RqdError`.
- [ ] Step 3: `uv run pytest -q` → expected: same 94 tests pass (now split across `common/tests` and `SourceScout/tests`), `uv run sourcescout --help` works, `git grep ScoutError` empty.
- [ ] Step 4: commit `refactor: move shared code into common/rqd`.

### Task 2: `rqd.claude_code` agent mode

**Produces:** `ClaudeCodeClient.run_agent(*, model, effort, system, user, schema, tools: list[str], max_budget_usd: float) -> AgentResult` where `AgentResult(structured_output: dict, tool_calls: list[ToolCall(name, input)], usage: dict, cost_usd: float, num_turns: int, duration_s: float, transcript: str)`. Shares argument building, env stripping and error classification with `messages.create` (one `_invoke` core). Uses `--output-format stream-json --verbose`, `--tools`/`--allowedTools` from `tools`, `--max-budget-usd`. Tool calls are counted from `assistant` events' `tool_use` blocks (not from `server_tool_use`, which reports 0 — measured). Result event = last `type == "result"` line. Errors: auth/usage-limit → `ExtractionConfigError`; budget exhausted (`subtype` contains `budget` or `terminal_reason` contains `budget`), other agent errors, no structured output, timeout (`AGENT_TIMEOUT_S = 1800`) → `ItemExtractionError` carrying the transcript.

- [ ] Tests (`common/tests/test_rqd_claude_code.py`, fake runner returning recorded stream-json): args contain tools/allowedTools/budget/stream-json and no API key in env; tool calls counted (WebSearch×2, WebFetch×1, StructuredOutput excluded from the search count by the caller); budget-exceeded result → `ItemExtractionError`; 429 → `ExtractionConfigError`; missing result line → `ItemExtractionError`.
- [ ] Implement; run full suite; commit `feat(rqd): claude_code agent mode with tool-call accounting`.

### Task 3: Problem Extractor — config, schema, similarity, state, records

**Files:** `ProblemExtractor/config.yaml` (`extraction: {model: claude-opus-5-5, effort: low, token_budget: 600, shortlist_size: 5}`, `sourcescout_root: ../SourceScout`), `problem_schema.yaml` (record example from spec §4.3), `problemextractor/{config,schema,similarity,state,records}.py`.
- `schema.py`: `PEOutput` pydantic model = spec §4.2 (`merge_with: str | None`, `merge_reason`, `problem.precise_statement`, `current_state.known_solution`, `failure.what_current_methods_cannot_do`, `desired_capability`, `why_it_matters`, `unsolvedness{explicit, explicit_evidence="", inferred}`); `PE_SCHEMA = rqd.config.api_schema(PEOutput)` — `api_schema`/`_sanitize` move from `sourcescout/schema.py` into `rqd/config.py` (shared, not copied).
- `similarity.py`: `shortlist(query: str, docs: dict[str, str], k: int) -> list[str]` — TF-IDF (lowercase word tokens, stopwords removed, smooth idf) cosine; deterministic tie-break by id.
- `state.py`: SQLite `ProblemExtractor/data/pe.db`, table `processed(candidate_id PK, problem_id, decision, at)`; `is_processed`, `record`.
- `records.py`: `ProblemRecord` load/save YAML under `problems/`; `new_problem(candidate, out, run)`, `merge_into(record, candidate, out, reason, run)` (appends `sources`, `merge_log` with `extracted`, bumps `revision`, keeps text fields); `all_problems()`; problem id `prob-` + first 12 hex of the first candidate's item id + `-` + candidate index.
- [ ] Tests `test_pe_similarity.py` (identical text ranks first; unrelated excluded order stable; empty corpus → []), `test_pe_records.py` (new/merge/revision/merge_log extracted; save/load roundtrip), `test_pe_state.py`.
- [ ] Implement; commit `feat(pe): schema, similarity shortlist, state and records`.

### Task 4: Problem Extractor — extraction run and CLI

**Files:** `problemextractor/extract.py`, `problemextractor/cli.py`, `ProblemExtractor/README.md`, pyproject script `problemextractor`.
- `extract.py`: `new_candidates(ss_output_dir, state, registry)` → candidate records not processed, ordered by tier then `extracted_with.at`; `build_params(cfg, candidate, item_text, shortlist)` → `messages.create` params (system prompt: document-only, "not stated", ≤60 words/field, merge rules, shortlist listed as `[prob-id] statement`); `process(candidate, client)`: call, validate `PEOutput`; `merge_with` not in shortlist → treat as new + report line; verify `explicit_evidence` with `rqd.quotes.quote_in_text` against item text; write/merge record; `state.record`; report stats (candidates, new, merged, invalid_merge, unverified, output tokens, tokens/candidate vs budget). Item text from `sourcescout.store.Store(ss_root/data/scout.db).get(item_id)`; missing item → per-candidate failure (reported). Per-candidate `ItemExtractionError` → failure recorded, candidate *not* marked processed (retried next run).
- `cli.py`: `run [--limit N]`, `list [--sort sources|tier]`, `show <id>`; uses `rqd.cli` helpers; progress logger `problemextractor`; run report printed + saved to `data/runs/`.
- [ ] Tests `test_pe_extract.py` with fake `messages.create` client: new problem written; second similar candidate merged (shortlist contains first); invalid merge id → new + reported; "not stated" kept; explicit evidence verified/unverified; idempotent second run (0 processed); failure not marked processed; tier order; `test_pe_cli.py` list/show/lock/clean error.
- [ ] Implement; commit `feat(pe): extraction run with merging and CLI`.

### Task 5: Novelty Investigator — schema, prompt, verification

**Files:** `NoveltyInvestigator/config.yaml` (`agent: {model: claude-opus-5-5, effort: medium, max_budget_usd: 2.0, min_searches: 4}`, `http` section, `problemextractor_root: ../ProblemExtractor`), `novelty_schema.yaml`, `noveltyinvestigator/{config,schema,prompt,verify}.py`; `rqd/http.py` gains `pdf_to_text(bytes) -> str` (pypdf) and `Fetcher` returns bytes+content-type via existing `get` (response object).
- `schema.py`: `NIOutput` = spec §5.3 model-produced part: `novelty.status` enum, `checks` (five, each `{answer: yes|no|partially|unclear, reasoning, evidence: list[int]}` plus `obvious_baseline.baseline`), `closest_work[{title, url, year: int|None, kind enum, quote, how_close}]`, `difference_from_closest_work`, `strongest_counterargument`, `confidence: float`. Search counts/verification are NOT in the model schema.
- `prompt.py`: adversarial system prompt (spec §5.2) incl. the six questions, source families, "never answer from memory; at least {min_searches} WebSearch queries; WebFetch pages you cite; quote only text you read; no ellipses"; `render_problem(record)`.
- `verify.py`: `verify_work(fetcher, url, quote) -> "verified"|"quote_not_found"|"unfetchable"` (HTML→`html_to_text`, `application/pdf`→`pdf_to_text`; `SourceFetchError` → unfetchable).
- [ ] Tests `test_ni_verify.py` (HTML verified; quote absent; 404; robots; PDF bytes built with pypdf writer... if pypdf cannot write text, use a small checked-in PDF fixture generated once with `reportlab`-free minimal PDF bytes), `test_ni_schema.py` (sanitized schema valid; confidence range not in API schema but validated in Pydantic `ge=0, le=1`).
- [ ] Implement; commit `feat(ni): schema, adversarial prompt and evidence verification`.

### Task 6: Novelty Investigator — investigate command, records, CLI

**Files:** `noveltyinvestigator/{records,investigate,cli}.py`, README, pyproject script `noveltyinvestigator`.
- `investigate.py`: `investigate(problem_id)`: load PE record (missing → `RqdError` with fix "see problemextractor list"); `run_agent` with tools `["WebSearch","WebFetch"]`; count `searches` = WebSearch calls, `fetches` = WebFetch calls, `queries` from WebSearch inputs; validate `NIOutput`; verify each `closest_work`; build record (spec §5.3) incl. `search.sufficient`, `verified_fraction`, `investigated_with`; existing file → previous revision summary appended to `history`, `revision+1`; save transcript to `data/transcripts/<problem-id>-<run>.jsonl`. Multi-id command: `ItemExtractionError` per problem reported, continue; `ExtractionConfigError` stops.
- `cli.py`: `investigate <ids…>`, `list` (status, confidence, verified_fraction, `INSUFFICIENT SEARCH` marker), `show <id>`.
- [ ] Tests `test_ni_investigate.py` with fake agent runner (recorded stream-json incl. tool_use events) + mocked HTTP: record fields; searches counted; insufficient search flag; re-investigation history; budget error → no file + continue with next id; usage limit → stop; transcript saved. `test_ni_cli.py`: list/show/unknown problem clean error.
- [ ] Implement; commit `feat(ni): investigate command with verified evidence`.

### Task 7: Live verification, docs, review, PR

- [ ] `common` + PE + NI live tests (`-m live`): PE on 3 real SourceScout candidates (from a copy of the live SourceScout output+db); NI on one toy known-solved problem ("predict 3D protein structure from sequence at near-experimental accuracy" → expect `solved`/`partially_solved`, searches ≥ min_searches, ≥1 verified work).
- [ ] Real run: `problemextractor run` on the live candidates (copy of data, not the user's checkout), inspect merges; `noveltyinvestigator investigate` on 1–2 real problems; record cost/time.
- [ ] READMEs, root README section; final whole-branch review (fresh reviewer, most capable model); fix Critical/Important test-first; PR.
