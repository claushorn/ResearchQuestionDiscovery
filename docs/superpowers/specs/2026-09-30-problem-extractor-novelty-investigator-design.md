# Problem Extractor & Novelty Investigator — Design Spec

Date: 2026-09-30
Status: draft, awaiting review
Builds on: `docs/superpowers/specs/2026-09-30-sourcescout-design.md`

## 1. Purpose and pipeline position

```
SourceScout ──candidates──> Problem Extractor ──problems──> [user picks] ──> Novelty Investigator
 (collect)                   (precise, merged problems)                        (adversarial: try to kill)
                                                  later: Economic value → Personal fit → Opportunity generator
```

- **Problem Extractor (PE)** turns SourceScout candidates into precise,
  *merged* problem records: one record per distinct problem, however many
  sources state it. It extracts from the source documents only; it does not
  judge novelty, value or fit.
- **Novelty Investigator (NI)** is adversarial. Its goal is to kill an
  opportunity by finding evidence that it is already solved, merely an
  implementation issue, or has an obvious baseline. It runs only on problems
  the user picks.

### Success criteria

1. `problemextractor run` processes every new SourceScout candidate exactly
   once; re-running with no new candidates does nothing.
2. Near-duplicate candidates end up in one problem record whose `sources`
   list all of them; each merge decision is logged with a reason.
3. PE never invents content: a field not stated in the source is `"not stated"`;
   `unsolvedness.explicit: true` requires a verbatim quote that is verified.
4. `noveltyinvestigator investigate <problem-id>` produces an investigation
   with the user's output schema. At least `min_searches` web searches must
   have run, or the investigation is marked `insufficient_search`. Every cited
   work's quote is checked by fetching its URL.
5. Token/cost figures are reported per PE run and per investigation.

## 2. Scope

**In:** shared package extraction (refactor out of SourceScout), PE, NI.
**Out (roadmap):** Economic value investigator, Personal-fit investigator,
Opportunity generator; automatic NI triggering; patents via API (patents are
reached through web search, e.g. Google Patents pages); Google Scholar
(no API; scraping violates its terms; Semantic Scholar / OpenAlex / arXiv pages are
reached through web search instead).

## 3. Layout

Each capability has its own directory; shared code lives in one package.

```
ResearchQuestionDiscovery/
  common/rqd/                shared library (moved out of SourceScout, not copied)
    errors.py                RqdError(message, fix) base; ConfigError; ExtractionConfigError;
                             ItemExtractionError; SourceFetchError
    config.py                Strict model base, load_yaml
    timeutil.py              utcnow, iso
    http.py                  Fetcher (robots, throttle), html_to_text (+ pdf_to_text for NI)
    quotes.py                quote_in_text (NFKC, quote/dash/whitespace normalisation)
    claude_code.py           ClaudeCodeClient (generalised: tools, budget, stream-json)
    cli.py                   clean_errors, exclusive (run lock), progress_to_stderr, dotenv loading
  SourceScout/               unchanged behaviour; imports the moved code from rqd
  ProblemExtractor/
    config.yaml  problem_schema.yaml  README.md
    problemextractor/        package
    tests/
    problems/<problem-id>.yaml          versioned output
    data/                               state + run reports (git-ignored)
  NoveltyInvestigator/
    config.yaml  novelty_schema.yaml  README.md
    noveltyinvestigator/     package
    tests/
    investigations/<problem-id>.yaml    versioned output
    data/                               raw transcripts + run reports (git-ignored)
```

One uv project (root `pyproject.toml`) with packages `rqd`, `sourcescout`,
`problemextractor`, `noveltyinvestigator` and one CLI per capability.
The refactor starts after PR #4 (relevant links, tier order) is merged, so it moves the current code. It is a pure move: SourceScout's test suite must pass unchanged
(apart from import paths) before PE work starts. `ScoutError` becomes
`RqdError` everywhere (no alias kept).

## 4. Problem Extractor

### 4.1 Input

- New SourceScout candidate files (`SourceScout/output/*/*.yaml`). "New" =
  `candidate_id` not yet in PE's state DB (`ProblemExtractor/data/pe.db`,
  table `processed(candidate_id, problem_id, decision, at)`).
- The candidate's source item text, read through SourceScout's `Store`
  (read-only, by `item_id`). PE does not re-fetch sources.
- Candidates are processed in source-tier order (A, then B, then C), matching
  SourceScout.

### 4.2 Extraction + merge (one `claude -p` call per candidate)

Input to the model: the candidate record, the source item text, and a
shortlist of the 5 most similar existing problems (TF-IDF cosine similarity
over `precise_statement` + `desired_capability`, computed in code; each
shortlisted problem shown as id + statement).

Output schema (structured output):

```yaml
merge_with: prob-… | null        # an id from the shortlist, or null for a new problem
merge_reason: ...                # one sentence
problem:
  precise_statement: ...
current_state:
  known_solution: ...            # or "not stated"
failure:
  what_current_methods_cannot_do: ...   # or "not stated"
desired_capability: ...
why_it_matters: ...
unsolvedness:
  explicit: true|false
  explicit_evidence: "<verbatim quote>"  # required when explicit
  inferred: true|false                   # model's inference, flagged as such
```

Rules in the prompt: extract only from the document; no outside knowledge;
"not stated" instead of guessing; ≤ 60 words per field; `merge_with` only when
it is the *same* problem (same desired capability and failure), not merely the
same area. `merge_with` values that are not in the shortlist are rejected
(treated as `null` and reported), not silently accepted.

### 4.3 Problem record `ProblemExtractor/problems/<problem-id>.yaml`

```yaml
problem_id: prob-<12 hex>        # from the first candidate's id; stable
revision: 3                       # increments when sources are added
problem: {precise_statement: ...}
current_state: {known_solution: ...}
failure: {what_current_methods_cannot_do: ...}
desired_capability: ...
why_it_matters: ...
unsolvedness: {explicit: true, inferred: false, explicit_evidence: ..., evidence_verified: true}
sources:                          # one entry per merged candidate
  - candidate_id: cand-…
    source_id: grants-gov-ml
    tier: A
    url: ...
    payment_signal: {type: grant, stated: "$1.5M", deadline: 2026-12-01}
merge_log:
  - {candidate_id: cand-…, decision: new | merged, reason: ..., extracted: {<the six fields as extracted from this candidate>}}
extracted_with: {model, run_id, output_tokens, at}
```

A merge appends to `sources` and `merge_log` and increments `revision`; the
first extraction's text fields stay (no silent rewrite). The fields
extracted from the merged candidate are kept in the merge log entry
(`extracted`) so nothing is lost and a later stage can re-synthesise.

### 4.4 Commands

```
uv run problemextractor run [--limit N]          # process new candidates
uv run problemextractor list [--sort sources|tier]   # id, statement, #sources, best payment signal
uv run problemextractor show <problem-id>
```

### 4.5 Budget

`extraction.token_budget` in `ProblemExtractor/config.yaml` (default 600
output tokens per candidate), reported per run like SourceScout.

## 5. Novelty Investigator

### 5.1 Invocation

```
uv run noveltyinvestigator investigate <problem-id> [<problem-id> ...]
uv run noveltyinvestigator list            # investigated problems, status, confidence
uv run noveltyinvestigator show <problem-id>
```

Only problems the user names are investigated. Re-investigating writes a new
revision of the investigation file (previous kept in the file's `history`).

### 5.2 Agent run

One `claude -p` session per problem:

- `--safe-mode`, `--tools WebSearch,WebFetch`, `--allowedTools WebSearch,WebFetch`,
  `--output-format stream-json --verbose`, `--max-budget-usd <config>`,
  model/effort from config (default `claude-opus-5-5`, `medium`),
  API-key variables stripped (subscription billing).
- System prompt (adversarial): the goal is to kill the opportunity; never
  answer from memory; run at least `min_searches` searches (default 4) across
  papers (arXiv, Semantic Scholar/OpenAlex pages), GitHub, benchmarks,
  technical reports, patents, company publications; open (WebFetch) the
  pages you cite and quote text you read; answer the six questions.
- Input (stdin): the problem record (statement, known solution, failure,
  desired capability, why it matters, source URLs).

### 5.3 Output schema `NoveltyInvestigator/investigations/<problem-id>.yaml`

The user's schema, extended with per-question answers and evidence:

```yaml
problem_id: prob-…
revision: 1
novelty:
  status: likely_open | partially_solved | solved | unclear
checks:                                  # the six questions
  already_solved:            {answer: yes|no|partially|unclear, reasoning: ..., evidence: [<closest_work index>]}
  same_problem_paper:        {...}
  merely_implementation_issue: {...}
  obvious_baseline:          {answer: ..., baseline: ..., evidence: [...]}
  obvious_approaches_tried:  {...}
closest_work:
  - title: ...
    url: ...
    year: 2025
    kind: paper | repo | benchmark | patent | report | company
    quote: "<verbatim text read on that page>"
    how_close: ...
    verification: verified | quote_not_found | unfetchable     # set by our code, not the model
difference_from_closest_work: ...
strongest_counterargument: ...
confidence: 0.74
search:
  searches: 6            # counted from the stream-json tool calls, not self-reported
  fetches: 4
  queries: [...]         # as issued
  sufficient: true       # searches >= min_searches
verified_fraction: 0.75  # closest_work entries with verification == verified
investigated_with: {model, effort, cost_usd_equivalent, output_tokens, input_tokens, turns, duration_s, at}
history: []             # earlier revisions (novelty, confidence, investigated_with) when re-investigated
```

### 5.4 Verification (our code, after the agent finishes)

For every `closest_work` entry: fetch `url` with the shared polite `Fetcher`
(HTML → `html_to_text`; `application/pdf` → `pdf_to_text`), check `quote`
with the shared `quote_in_text`. Outcomes: `verified`, `quote_not_found`
(page fetched, quote absent), `unfetchable` (HTTP error, robots, timeout).
Arxiv `abs/`, `html/` and `pdf/` URLs are all fetched as given (no rewriting).

Measured on 2026-09-30: the model sometimes labels a quote "search-result summary; page
not opened" and joins fragments with "…"; such quotes fail verification by
design and show as `quote_not_found`.

### 5.5 Failure handling

- `searches < min_searches` → investigation saved with
  `search.sufficient: false` and reported; `novelty.status` is kept but the
  `list` view marks it `INSUFFICIENT SEARCH`.
- Budget exhausted (`--max-budget-usd`) or other agent error → no
  investigation file written; the error is reported per problem; other
  problems in the same command continue.
- Subscription usage limit / not logged in → the command stops cleanly
  (`ERROR:`/`Fix:`), as in SourceScout.
- Raw `stream-json` transcript saved to `NoveltyInvestigator/data/transcripts/`
  for audit (git-ignored).

### 5.6 Cost

Measured probe (2 searches, 1 fetch): ~26 s, $0.13 list-equivalent, ~11k input
/ 1.6k output tokens. A full investigation is expected at roughly $0.5–2
equivalent and 2–5 minutes; default cap `max_budget_usd: 2.0`
(`NoveltyInvestigator/config.yaml`). On the subscription this counts against
plan limits, not money.

## 6. Mapping to `opportunities/research_opportunity_schema.yaml`

| Opportunity field | Filled by |
|---|---|
| `problem.statement`, `current_solution`, `limitation` | PE (`precise_statement`, `known_solution`, `what_current_methods_cannot_do`) |
| `problem.evidence`, `source` | PE `sources` (from SourceScout candidates) |
| `unsolved_claim.claim`, `evidence_for` | PE `unsolvedness` + NI `closest_work` (`likely_open`) |
| `unsolved_claim.evidence_against`, `confidence` | NI `strongest_counterargument`, `confidence` |
| `competitors`, `related_work` | NI `closest_work` |
| `economic_value`, `user_fit`, `technical` | later stages |

The Opportunity generator (later) assembles records by `problem_id`; neither
PE nor NI writes opportunity files.

## 7. Shared rules

Typed errors with clean `ERROR:`/`Fix:` output; external failures recorded
and reported without stopping the run; progress on stderr, report on stdout;
one run lock per capability directory; `ANTHROPIC_API_KEY` stripped from
`claude` subprocesses; every quote verified; `"not stated"` over invention.

## 8. Testing

- Refactor: SourceScout suite green after the move (imports only changed).
- PE: fake `claude -p` runner; merge shortlisting (TF-IDF) deterministic tests;
  invalid `merge_with` rejected; "not stated" passthrough; explicit
  unsolvedness quote verified/unverified; idempotent re-run; tier order.
- NI: fake runner emitting recorded `stream-json` transcripts; search counting
  from tool-call events; `insufficient_search`; verification outcomes with
  mocked HTTP (HTML, PDF, 404, robots); budget-exhausted path; usage-limit
  stop; one live test (`-m live`) on a known-solved toy problem expecting
  `solved`/`partially_solved` and ≥ `min_searches` searches.
