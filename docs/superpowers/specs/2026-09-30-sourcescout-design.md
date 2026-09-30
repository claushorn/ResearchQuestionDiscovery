# SourceScout — Design Spec

Date: 2026-09-30
Status: draft, awaiting review

## 1. Purpose

SourceScout is the first stage of the ResearchQuestionDiscovery pipeline. It
**collects** candidate *newly exposed technical problems that somebody has a
reason to pay to solve*, from sources where organisations state problems and
attach (explicitly or implicitly) money to them.

SourceScout is deliberately shallow. It finds, fetches, de-duplicates and
extracts. It does **not** estimate economic value, score, rank, triage or match
against `capabilities.yaml` / `interests.yml`; those are later, separate
stages that consume SourceScout's output.

### Success criteria (v1)

1. `uv run sourcescout scan` fetches every `active` source in the registry and
   stores each item once; a re-run with unchanged sources yields zero new items.
2. `uv run sourcescout extract` turns every new item into 0..N candidate records
   conforming to `SourceScout/scout_output_schema.yaml`, each with a verbatim
   evidence quote that is verified to occur in the source text.
3. Extraction output is **≤ 500 tokens per candidate** (target 300–500),
   measured from API `usage.output_tokens` and reported per run.
4. The registry updates itself: new sources are discovered from scanned
   content, enter as `candidate`, and are promoted or retired by explicit rules.
5. A single failing source never aborts a run; it is recorded and reported.

## 2. Scope

**In v1 (ingested):**

- Tier A — explicitly funded problems: government solicitations (SBIR/STTR,
  grants.gov, ARPA-H, UK ARIA, EU Funding & Tenders), challenge/prize
  platforms (Kaggle, DrivenData, AIcrowd, HeroX, Zindi, Adaptyv).
- Tier B — implied payment: public job boards (Greenhouse, Lever, Ashby) of a
  seeded company list; VC "requests for startups" (YC RFS).
- Tier C — stated problems, value inferred: engineering-blog RSS feeds,
  applied-ML workshop calls for papers / industry-track pages.

**Out of v1:** Tier D (academic limitations mining), Tier E (HN, forums,
newsletters), X.com and LinkedIn (paid/ToS-restricted, fragile), economic
value estimation, triage, deep analysis of any kind.

## 3. Architecture

```
sources.yaml (categories) ─┐
registry.yaml (sources) ───┴─> scan ──> adapters ──> RawItem ──> store (SQLite)
                                                                     │ new/changed items
                                                                     v
                                    extract (Claude API, Batch) ──> candidates/*.yaml
                                                                     │ links of productive items
                                                                     v
                                                       discover ──> registry.yaml (candidate)
```

Package: `SourceScout/sourcescout/`, uv project rooted at
`ResearchQuestionDiscovery/` (its own git repository).

### 3.1 Source categories — `SourceScout/sources.yaml`

Kept, and restructured from a flat list into the **high-level category
classes** that future rounds can activate. Each category:

```yaml
categories:
  - id: gov_solicitation
    tier: A
    description: Government funding calls with stated problem + budget
    enabled: true          # ingested in this round
  - id: academic_limitations
    tier: D
    description: Limitations / future-work sections of papers
    enabled: false         # future round
```

The existing entries (papers, arxiv, conference papers, conference workshops,
benchmark leaderboards, GitHub issues, technical blogs, AI lab publications,
startup technical blogs, research competitions) are migrated into categories;
v1 categories are added. `sources.yaml` answers *what kinds of places* we
scan; it holds no URLs.

### 3.2 Source registry — `SourceScout/registry.yaml`

The single source of truth for *concrete* sources. Each entry references one
category id from `sources.yaml` (validated at load; unknown id → error).

```yaml
- id: sbir-topics
  name: SBIR.gov open topics
  category: gov_solicitation
  kind: html_list          # adapter
  url: https://www.sbir.gov/topics?status=1
  params: {link_selector: 'a[href^="/topics/"]'}
  cadence_hours: 24
  status: active           # active | candidate | retired
  provenance: seeded       # seeded | discovered_from:<item-id>
  health: {last_ok: null, consecutive_failures: 0, last_error: null}
  yield: {scans: 0, items_seen: 0, candidates: 0}
```

Only sources in an `enabled` category and with `status` `active` or
`candidate` are scanned. Registry writes are done by the tool (load → modify →
atomic rewrite); manual edits are allowed and validated on load.

### 3.3 Adapters

One class per `kind`, interface
`fetch(source) -> list[RawItem]`, where
`RawItem = (source_id, url, title, published, text)`.

| kind | Covers |
|---|---|
| `rss` | engineering blogs, funder news feeds, any RSS/Atom |
| `greenhouse`, `lever`, `ashby` | public job-board JSON endpoints |
| `grants_gov` | grants.gov `search2` + `fetchOpportunity` APIs |
| `html_list` | listing page + CSS selector for item links, then fetch each unseen item page (SBIR topics, challenge platforms, ARPA-H, ARIA, workshop CFPs) |
| `page` | one page = one item (YC RFS, single CFP pages) |

The SBIR.gov public API returned HTTP 403 on 2026-09-30; SBIR topics are scanned
from the static `sbir.gov/topics` listing via `html_list`. `html_list` never collects finished items: `skip_link_text` (entries the listing marks
ended/closed/completed; every link to such a URL is skipped) and `stop_at_heading` (nothing
below e.g. a "Completed competitions" heading); challenge sources use them, or the site's own
active filter (AIcrowd `?challenge_filter=active`). Every kind accepts
`title_include` / `title_exclude` regex params (job-board sources without
their own `title_include` use `config.yaml` `scan.job_title_include`) (deterministic pre-filter, e.g.
to skip non-research job ads before any LLM call).

Common HTTP layer: one shared client with a descriptive User-Agent,
robots.txt check, per-host rate limit, timeout, and HTML→text conversion.
Item text is truncated **only** by an explicit, logged per-source cap
(`max_chars`), never silently. A failed fetch of one item page (html_list,
full-text RSS) is recorded as an item error; the rest of the source is kept.
Selectors and regexes in `params` are validated when the registry loads.

### 3.4 Store — `SourceScout/data/scout.db` (SQLite)

Table `items`: `item_id` (hash of canonical URL), `source_id`, `url`, `title`,
`published`, `content_hash`, `text`, `first_seen`, `last_seen`,
`extract_status` (`pending` | `done` | `failed`), `extract_error`.

- An item is **new** when its canonical URL is unseen → `pending`.
- Pending items are extracted in source-tier order (A, then B, then C), oldest first within a tier.
- An item is **changed** when its `content_hash` differs → `pending` again,
  and its candidates are marked `revision: n+1`.
- Otherwise only `last_seen` updates.

The store holds item state only; candidate records live only in YAML (§3.6).

### 3.5 Extractor

- Claude API, Python `anthropic` SDK, `client.messages.parse` with a Pydantic
  model (structured outputs) mirroring `scout_output_schema.yaml`.
- Backend (`extraction.backend`): `api` (Anthropic API key, pay per token,
  Message Batches) or `claude_code` (`claude -p --safe-mode` on the user's
  Claude subscription; sync only; API-key variables are stripped from the
  subprocess so billing cannot silently switch). Both return the same
  message shape into one response-handling path.
- Model and effort are configured in `SourceScout/config.yaml`; default
  `claude-opus-5-5`, effort `low`. The model choice is the user's; no silent
  cheaper-model cascade.
- Static extraction instructions + schema form a cached prompt prefix;
  per-item text follows it.
- `extract --batch` submits all pending items via the Message Batches API
  (50 % cost) and collects results keyed by `custom_id = item_id`;
  `extract` without `--batch` runs synchronously (for small runs/tests).

**Shallowness / token budget.** The Scout extracts what the source says; it
does not analyse, estimate value, or speculate. Enforced by:

1. Prompt: extract only what is stated; no assessments beyond one sentence.
2. Length limits: `candidate_problem.statement` ≤ 60 words,
   `why_interesting` ≤ 1 sentence (≤ 30 words), `evidence` quotes ≤ 50 words
   each, ≤ 2 quotes, `technical_area` ≤ 3 tags. Structured outputs cannot
   express length constraints, so word limits are instructed in the prompt and
   **reported** per candidate (`length_violations`); count caps are enforced by
   Pydantic on the client.
3. At most 3 candidates per item (validation failure otherwise).
4. Often-empty fields (deadline, evidence, researchers) are optional: `claude -p`
   validates structured output after generation and makes the model rewrite the
   whole JSON when a required field is omitted (measured: about 2x tokens). The model does not
   copy URLs; discovery uses the stored item links. Measured 2026-09-30 on 10
   items: 385 output tokens per candidate, 0 retries (was 509 with retries).
5. `max_tokens = 4000` per request (hard stop against runaway output), and the run report
   shows output tokens of productive items per candidate per source; tokens
   spent on items without candidates are reported separately (`empty_tok`). A run whose mean exceeds 500
   is reported as a budget violation (the numbers are shown, not hidden).

Note: on `claude-opus-5-5` thinking cannot be disabled; its tokens count as
output. Effort `low` keeps it small; the measured number decides whether the
budget holds.

**Evidence verification.** Every quote is checked (whitespace-normalised
substring match) against the item text. Unmatched → the candidate is written
with `evidence_verified: false`; it is never silently accepted or dropped.

**Batch resume.** Submitted items are marked `submitted` with their batch id;
the next `extract --batch` first collects any such batch (expired/canceled
items and server-side errors return to `pending`; `invalid_request_error`
fails the item), so an interrupted wait loses nothing. A batch the API no
longer returns (404, e.g. past result retention) has its items returned to
`pending` and is reported. Every report shows item-state totals
(pending/submitted/done/failed); `extract --retry-failed` returns failed
items to `pending`.

**Errors.** Per-item API refusal or schema failure → `extract_status: failed`
with the error, listed in the run report. Auth/config errors raise a typed
exception (§3.9).

### 3.6 Output — `SourceScout/output/YYYY-MM/<candidate-id>.yaml`

One file per candidate, conforming to `scout_output_schema.yaml`, which is
extended with the fields below (schema file updated accordingly):

```yaml
source_id: src-...          # registry id
item_id: ...                # store id
candidate_id: cand-...
revision: 1
source: {url, title, date, tier, category}
candidate_problem: {statement}
why_interesting: ...        # one sentence, stated not analysed
explicit_unsolved_signal: {present, evidence}
payment_signal:             # raw, as stated; not scored
  type: prize | grant | contract | hiring | investor_thesis | none_stated
  stated: "e.g. Phase I up to $250k"
  evidence: "<verbatim quote>"
  deadline: 2026-12-01 | null
technical_area: [...]
entities: {organizations: [...], researchers: [...]}
evidence_verified: true
extracted_with: {model, run_id, output_tokens}
```

### 3.7 Registry maintenance (`discover`)

- Input: each candidate's `referenced_urls` (job-board patterns and feed
  autodiscovery). The model returns only the numbers of up to 5 relevant links
  from the item's numbered link list; code resolves them to URLs, so the model
  never copies URLs. Plus outbound links of newly seen items (job-board
  patterns only). Unmapped URLs are deduplicated by canonical URL and by host
  without `www.`. plus outbound links of newly seen items (job-board patterns
  only; no fetching).
- Deterministic detection only: RSS/Atom autodiscovery
  (`<link rel="alternate">`), Greenhouse/Lever/Ashby URL patterns, and domains
  matching an `html_list` pattern already in the registry.
- New sources are added as `status: candidate`, `provenance: discovered_from:<item-id>`,
  mapped to a category; unmappable ones go to `SourceScout/discovered_unmapped.yaml`
  for manual review, not guessed.
- Promotion: `candidate → active` on its first candidate; retired if none
  within its first `promote_within_scans = 5` scans. Active sources are retired
  after `max_consecutive_failures = 5` failed fetches or
  `retire_zero_yield_active = 20` scans without a candidate. Only scans that
  stored new or changed items count toward zero-yield retirement, so a stable
  page (a CFP, an RFS list) is not retired merely for not changing. A scan
  attempt (successful or not) sets `last_scanned`, so failing sources are
  retried on their cadence. Every transition
  is logged in the run report; all three numbers are in `config.yaml`.

### 3.8 CLI

```
uv run sourcescout scan    [--tier A] [--category ID] [--source ID]
uv run sourcescout extract [--batch] [--limit N]
uv run sourcescout discover
uv run sourcescout sources list|promote ID|retire ID
uv run sourcescout run     # scan → extract --batch → discover → report
uv run sourcescout report  [--run ID]
```

A cron job or a later agent skill wraps `run`.

### 3.9 Error handling

- External, per-source failures (timeouts, HTTP errors, robots disallow,
  parse errors of a feed) → recorded in `health`, listed in the report; run
  continues.
- Internal/deterministic failures (invalid registry/config, unknown category,
  missing API credentials — checked up front because the SDK otherwise fails
  with a bare `TypeError` at the first request, schema mismatch, API
  authentication/permission/400 errors) → typed exceptions
  (`RegistryError`, `ConfigError`, `ExtractionConfigError`); the CLI catches
  them and prints a clean message + fix, exit code 1, no traceback.
  Unexpected exceptions propagate with traceback.

## 4. Testing

- Adapters: each tested against recorded fixtures (saved RSS/JSON/HTML) in
  `tests/fixtures/`; no network in the default suite.
- Store: new / unchanged / changed detection.
- Extractor: fake client returning fixed parsed output → schema conformance,
  evidence verification (matched and unmatched), per-candidate token
  accounting, max-3 cap; one opt-in live smoke test (`-m live`) that also
  asserts the ≤ 500 tokens/candidate budget on real sources.
- Registry: load validation (unknown category, duplicate id), lifecycle
  transitions, atomic rewrite.
- Discover: autodiscovery and job-board pattern detection on fixtures.

## 5. Seed set (v1)

~40–60 sources: Tier A ≈ 11 (listed in §2); Tier B ≈ 30 company job boards
chosen for the user's interests (AI labs; protein-design / biotech; operations
research, logistics, energy and quant firms — sequential decision-making) plus
YC RFS; Tier C ≈ 25 engineering-blog RSS feeds and applied-ML workshop pages.
Each seed URL is verified to fetch successfully before it is committed as
`active`; unreachable ones are left out and listed.

## 6. Open points decided by default

- Nested git repo in `ResearchQuestionDiscovery/` (done).
- Kaggle requires API credentials; if absent, Kaggle is scanned via its
  public listing page (`html_list`) instead — decided per source at seed time,
  not as a runtime fallback.
- Scheduling (cron/launchd) is out of scope for v1; `run` is the entry point.
