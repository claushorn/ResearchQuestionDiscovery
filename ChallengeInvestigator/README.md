# ChallengeInvestigator

For **finished challenges** SourceScout keeps (AIcrowd, DrivenData, Proteinbase — status `finished`): is it worth
trying to beat the best solution, and how?

```bash
uv run challenges headroom [<item-id> ...]    # gate; default: every finished challenge not checked yet
uv run challenges list                        # verdict + headroom %, winner/metric, investigated?, title
uv run challenges investigate <item-id> [...] [--force]
uv run challenges show <item-id>
```

1. **headroom** (deterministic, no agent): scrapes the final leaderboard (AIcrowd `/leaderboards` — the last round's
   main leaderboard, named in `leaderboard.label`; DrivenData's private leaderboard). Winner = rank 1; direction = the
   rank order, checked against `metric_bounds` in `config.yaml`, which also gives the ceiling by the metric's
   definition (log loss ≥ 0, accuracy ≤ 1, …); baseline = the strongest organisers' baseline row. Only when a
   lower-is-better leaderboard lists no baseline (DrivenData) does a small agent look it up (`baseline_agent`,
   ≤ $0.3; kept only if a verified quote states it). **Code** computes normalized headroom — higher-is-better
   `(ceiling − winner) / (ceiling − baseline)` (or `/ ceiling` without baseline), lower-is-better
   `(winner − ceiling) / (baseline − ceiling)` — and the verdict: `solved` (< `headroom_threshold`, 10%), `headroom`,
   `unclear` (metric not in `metric_bounds`, rank order contradicting it, no baseline, winner beyond the ceiling or
   worse than the baseline; never counted as solved), or `not_applicable` (source without a leaderboard scraper,
   e.g. Proteinbase, or no leaderboard page). A leaderboard whose layout is not the measured one fails that challenge.
2. **investigate** (picked; `solved` refused unless `--force`; runs the headroom check first if missing): the best
   solutions (winners' / top teams' code, write-ups, papers, forum winners posts) and the agent's improvement ideas
   (what they build on, why they could win, risks, effort).

No invented numbers: headroom values come from the leaderboard page or the metric's definition in config; a
looked-up baseline must be stated in a verified quote. In investigations, solutions without verified evidence are
dropped, a solution score is kept only if its quote or the scraped leaderboard (same team) states it;
decimals/percentages in the summary, approaches and ideas that neither a verified quote nor the headroom record
states are listed in `warnings.unsupported_numbers`; expected gains only as a labelled `expected_gain_assumption`.
Output: `challenges/<item-id>.yaml` (format: `challenge_schema.yaml`); transcripts in `data/transcripts/`.
