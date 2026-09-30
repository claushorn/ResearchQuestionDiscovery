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
                                                                     │ referenced_urls
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
  kind: sbir               # adapter
  url: https://api.www.sbir.gov/public/api/solicitations
  params: {open: 1}
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
| `sbir` | SBIR/STTR topics API |
| `grants_gov` | grants.gov search API |
| `html_list` | listing page + CSS selector for item links, then fetch each item page (challenge platforms, ARPA-H, ARIA, YC RFS, workshop CFPs) |

Common HTTP layer: one shared client with a descriptive User-Agent,
robots.txt check, per-host rate limit, timeout, and HTML→text conversion.
Item text is truncated **only** by an explicit, logged per-source cap
(`max_chars`), never silently.

### 3.4 Store — `SourceScout/data/scout.db` (SQLite)

Table `items`: `item_id` (hash of canonical URL), `source_id`, `url`, `title`,
`published`, `content_hash`, `text`, `first_seen`, `last_seen`,
`extract_status` (`pending` | `done` | `failed`), `extract_error`.

- An item is **new** when its canonical URL is unseen → `pending`.
- An item is **changed** when its `content_hash` differs → `pending` again,
  and its candidates are marked `revision: n+1`.
- Otherwise only `last_seen` updates.

The store holds item state only; candidate records live only in YAML (§3.6).

### 3.5 Extractor

- Claude API, Python `anthropic` SDK, `client.messages.parse` with a Pydantic
  model (structured outputs) mirroring `scout_output_schema.yaml`.
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
2. Schema length limits: `candidate_problem.statement` ≤ 60 words,
   `why_interesting` ≤ 1 sentence (≤ 30 words), `evidence` quotes ≤ 50 words
   each, ≤ 2 quotes, `technical_area` ≤ 3 tags.
3. At most 3 candidates per item.
4. `max_tokens = 4000` per request (hard stop against runaway output), and the run report
   shows `output_tokens / candidates` per source. A run whose mean exceeds 500
   is reported as a budget violation (the numbers are shown, not hidden).

Note: on `claude-opus-5-5` thinking cannot be disabled; its tokens count as
output. Effort `low` keeps it small; the measured number decides whether the
budget holds.

**Evidence verification.** Every quote is checked (whitespace-normalised
substring match) against the item text. Unmatched → the candidate is written
with `evidence_verified: false`; it is never silently accepted or dropped.

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
referenced_urls: [...]
evidence_verified: true
extracted_with: {model, run_id, output_tokens}
```

### 3.7 Registry maintenance (`discover`)

- Input: `referenced_urls` of new candidates plus outbound links of new items.
- Deterministic detection only: RSS/Atom autodiscovery
  (`<link rel="alternate">`), Greenhouse/Lever/Ashby URL patterns, and domains
  matching an `html_list` pattern already in the registry.
- New sources are added as `status: candidate`, `provenance: discovered_from:<item-id>`,
  mapped to a category; unmappable ones go to `SourceScout/discovered_unmapped.yaml`
  for manual review, not guessed.
- Promotion: `candidate → active` after ≥ 1 candidate within its first
  `N = 5` scans. Retirement: `→ retired` after `K = 5` consecutive fetch
  failures, or 0 candidates over the last 20 scans (active) / 5 scans
  (candidate). Every transition is logged in the run report. N, K are config.

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
  missing API credentials, schema mismatch) → typed exceptions
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
