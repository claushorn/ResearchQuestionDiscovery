# ChallengeInvestigator

For **finished challenges** SourceScout keeps (AIcrowd, DrivenData, Proteinbase — status `finished`): is it worth
trying to beat the best solution, and how?

```bash
uv run challenges headroom [<item-id> ...]    # gate; default: every finished challenge not checked yet
uv run challenges list                        # verdict + headroom %, winner/metric, investigated?, title
uv run challenges investigate <item-id> [...] [--force]
uv run challenges show <item-id>
```

1. **headroom** (short agent session, `headroom_agent.max_budget_usd` 0.5): metric and direction, winner score,
   ceiling, organisers' baseline. **Code** computes normalized headroom — higher-is-better
   `(ceiling − winner) / (ceiling − baseline)` (or `/ ceiling` without baseline), lower-is-better
   `(winner − ceiling) / (baseline − ceiling)` (needs a baseline) — and the verdict: `solved` (< `headroom_threshold`,
   10%), `headroom`, or `unclear` (winner or ceiling not backed; never counted as solved).
2. **investigate** (picked; `solved` refused unless `--force`; runs the headroom check first if missing): the best
   solutions (winners' / top teams' code, write-ups, papers, forum winners posts) and the agent's improvement ideas
   (what they build on, why they could win, risks, effort).

No invented numbers: winner and baseline must be stated in a verified quote (exact figure); a ceiling needs a
quote or a stated metric definition ("accuracy ≤ 1"); solutions without verified evidence are dropped, their scores
kept only if quoted; decimals/percentages in the summary, approaches and ideas that no verified quote states are
listed in `warnings.unsupported_numbers`; expected gains only as a labelled `expected_gain_assumption`.
Output: `challenges/<item-id>.yaml` (format: `challenge_schema.yaml`); transcripts in `data/transcripts/`.
