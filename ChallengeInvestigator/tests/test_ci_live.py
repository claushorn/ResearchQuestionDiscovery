"""Live layout guard: the scrapers still read the real leaderboards (run with `-m live`)."""
from pathlib import Path

import pytest

from challengeinvestigator.config import load_config
from challengeinvestigator.leaderboard import NoLeaderboard, fetch_leaderboard
from rqd.http import Fetcher

pytestmark = pytest.mark.live
CFG = load_config(Path(__file__).resolve().parents[1] / "config.yaml")


def test_live_aicrowd_chess_leaderboard():
    lb = fetch_leaderboard(Fetcher(CFG.http), "aicrowd", "https://www.aicrowd.com/challenges/global-chess-challenge-2025")
    assert lb.metric == "Average Centipawn Loss (ACPL)" and lb.ranked[0] == ("pranav_devarinti", 19.369)
    assert ("AIcrowd 4B SFT Fork to make your submission", 71.921) in lb.baselines and "Round 2" in lb.label


def test_live_drivendata_private_leaderboard():
    lb = fetch_leaderboard(Fetcher(CFG.http), "drivendata", "https://www.drivendata.org/competitions/143/tick-tick-bloom/")
    assert lb.metric == "Agg Root-mean-square error" and lb.ranked[0] == ("sheep", 0.7608) and len(lb.ranked) >= 10


def test_live_drivendata_judged_competition_has_no_leaderboard():
    with pytest.raises(NoLeaderboard):
        fetch_leaderboard(Fetcher(CFG.http), "drivendata", "https://www.drivendata.org/competitions/256/pale-blue-dot/")
