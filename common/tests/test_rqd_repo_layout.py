"""Everything the tools write is git-ignored, so `git pull` never collides with local runs (2026-10-01: the tools
rewrote the tracked SourceScout/registry.yaml and every pull touching it failed). Add a new stage's output here."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_OUTPUT = [
    "SourceScout/data/scout.db", "SourceScout/data/registry_state.yaml", "SourceScout/output/2026-09/cand-x.yaml",
    "SourceScout/discovered_unmapped.yaml",
    "ProblemExtractor/data/pe.db", "ProblemExtractor/problems/prob-x.yaml",
    "NoveltyInvestigator/data/transcripts/x.jsonl", "NoveltyInvestigator/investigations/prob-x.yaml",
    "EconomicValueInvestigator/data/scores.yaml", "EconomicValueInvestigator/assessments/prob-x.yaml",
    "ChallengeInvestigator/data/transcripts/x.jsonl", "ChallengeInvestigator/challenges/x.yaml",
    "PersonalFitInvestigator/data/transcripts/x.jsonl", "PersonalFitInvestigator/fits/prob-x.yaml",
    "OpportunityGenerator/data/transcripts/x.jsonl", "OpportunityGenerator/opportunities/OPP-0001.yaml",
    "OpportunityGenerator/briefs/OPP-0001.md", "personal_profile/cv.pdf",
    "Frontend/data/frontend.db", "Frontend/data/tasks/1.log",
]


@pytest.mark.parametrize("path", TOOL_OUTPUT)
def test_tool_output_is_git_ignored(path):
    assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0, f"{path} is not git-ignored"


def test_tracked_config_is_not_ignored():
    for path in ("SourceScout/registry.yaml", "SourceScout/sources.yaml", "ProblemExtractor/config.yaml", "Frontend/config.yaml"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 1, path
