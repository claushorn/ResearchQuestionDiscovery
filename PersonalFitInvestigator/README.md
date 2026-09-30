# PersonalFitInvestigator

"If this person attacked this problem tomorrow, what advantage would they have over a random strong ML researcher?"

```bash
uv run fit assess <problem_id> [...]   # one agent call per problem (no web), ≈ $0.1-0.3 list-price equivalent
uv run fit list                        # score /10, backed advantages, STALE (profile or problem changed), statement
uv run fit show <problem_id>
```

**Input:** the problem (ProblemExtractor), its Novelty investigation and EV assessment if they exist, and every
file in the profile directory. **Output:** `fits/<problem_id>.yaml` (format: `fit_schema.yaml`; git-ignored,
because fits quote the private profile verbatim).

## The profile: `personal_profile/` (repository root, git-ignored)

Free-form evidence about you, all of it read on every call (`.md`, `.txt`, `.yaml`, `.yml`, `.pdf`; limit
`profile_max_chars` in `config.yaml`). Useful: CV(s), publication list, a website snapshot, summaries of projects
and code you built, data or compute you have access to, contacts, facts that are in no CV, `capabilities.yaml`
(self-ratings) and `interests.yml`. The repository is public; the directory never enters git.

## Rules (code, not the model)

- An advantage names a profile file and quotes it verbatim (≥ 3 words); a quote not found in *that* file drops the
  advantage (warning).
- Advantages resting only on self-ratings (`self_rating_files`) cap the score at `self_rating_cap` (5); no backed
  advantage caps it at `no_advantage_cap` (2). The model's own score is kept as `stated_by_model`.
- An interest match needs its quote to be a whole line of a profile file (e.g. `interests.yml`), else it becomes `none`.
- A fit is STALE once the problem's revision or the profile (digest over all files) changed.
