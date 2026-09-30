# ResearchQuestionDiscovery
Multi-Agent System to catalog frontier open research questions of business interest

## Pipeline

| Capability | Directory | Command | Output |
|---|---|---|---|
| Collect candidate problems from funded calls, job boards, blogs | `SourceScout/` | `uv run sourcescout run` | `SourceScout/output/*/cand-*.yaml` |
| Precise, merged problem records | `ProblemExtractor/` | `uv run problemextractor run` | `ProblemExtractor/problems/prob-*.yaml` |
| Adversarial novelty check (problems you pick) | `NoveltyInvestigator/` | `uv run noveltyinvestigator investigate <id>` | `NoveltyInvestigator/investigations/*.yaml` |
| Economic value: who cares, is there money in it (problems you pick) | `EconomicValueInvestigator/` | `uv run economicvalue score` / `assess <id>` | `EconomicValueInvestigator/assessments/*.yaml` |
| Finished challenges: headroom gate, best solutions, ideas to beat them | `ChallengeInvestigator/` | `uv run challenges headroom` / `investigate <id>` | `ChallengeInvestigator/challenges/*.yaml` |

Shared code lives in `common/rqd`. LLM calls run through `claude -p` on your Claude subscription;
an `ANTHROPIC_API_KEY` in the git-ignored `.env` is only used by the `api` backend.
Roadmap: personal-fit investigator, opportunity generator.
