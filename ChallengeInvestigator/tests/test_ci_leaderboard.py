import pytest

from ci_testing import aicrowd_page, drivendata_page, drivendata_partial
from challengeinvestigator.leaderboard import LeaderboardError, NoLeaderboard, fetch_leaderboard, parse_aicrowd, parse_drivendata
from rqd_testing import make_fetcher

CHESS = aicrowd_page("Average Centipawn Loss (ACPL)",
                     [("pranav_devarinti", "19.369"), ("ivanchuks_fluffy_cat", "23.495"), ("AGI_noobs", "27.046")],
                     baselines=[("openai-gpt-5.2-low", "68.623"), ("AIcrowd 4B SFT Fork to make your submission", "71.921")])


def test_aicrowd_primary_column_ranked_rows_and_baseline_rows():
    lb = parse_aicrowd(CHESS, "https://www.aicrowd.com/challenges/chess/leaderboards")
    assert lb.metric == "Average Centipawn Loss (ACPL)" and lb.label == "Round 2 · Overall"
    assert lb.ranked == [("pranav_devarinti", 19.369), ("ivanchuks_fluffy_cat", 23.495), ("AGI_noobs", 27.046)]
    assert lb.baselines == [("openai-gpt-5.2-low", 68.623), ("AIcrowd 4B SFT Fork to make your submission", 71.921)]


def test_aicrowd_empty_score_cells_are_skipped():
    lb = parse_aicrowd(aicrowd_page("Score", [("a", "0.9"), ("b", "-"), ("c", "0.7")]), "u")
    assert lb.ranked == [("a", 0.9), ("c", 0.7)]


def test_unrecognised_layout_fails_loudly():
    with pytest.raises(LeaderboardError, match="score column"):
        parse_aicrowd(CHESS.replace("score-title", "x"), "u")
    with pytest.raises(LeaderboardError, match="no ranked rows"):
        parse_aicrowd(aicrowd_page("Score", []), "u")
    with pytest.raises(LeaderboardError, match="no leaderboard table"):
        parse_aicrowd("<html><body>nothing</body></html>", "u")


def test_drivendata_private_column():
    lb = parse_drivendata(drivendata_partial("Log Loss", [("TheAvengers", "0.2532"), ("NavAttack", "0.2731")]), "u")
    assert lb.metric == "Log Loss" and lb.label == "private leaderboard"
    assert lb.ranked == [("TheAvengers", 0.2532), ("NavAttack", 0.2731)] and lb.baselines == []


def test_drivendata_without_private_scores_is_not_final():
    with pytest.raises(LeaderboardError, match="private"):
        parse_drivendata(drivendata_partial("Log Loss", [("a", "0.3")], private=False), "u")


def test_fetch_aicrowd_and_drivendata():
    f = make_fetcher({"GET https://www.aicrowd.com/challenges/chess/leaderboards": CHESS,
                      "GET https://www.drivendata.org/competitions/1/dat/leaderboard/": drivendata_page("dat"),
                      "GET https://www.drivendata.org/competitions/1/dat/leaderboard_partial/?page=1":
                          drivendata_partial("Log Loss", [("TheAvengers", "0.2532")])})
    lb = fetch_leaderboard(f, "aicrowd", "https://www.aicrowd.com/challenges/chess")
    assert lb.url == "https://www.aicrowd.com/challenges/chess/leaderboards" and lb.ranked[0][0] == "pranav_devarinti"
    lb = fetch_leaderboard(f, "drivendata", "https://www.drivendata.org/competitions/1/dat/")
    assert lb.url == "https://www.drivendata.org/competitions/1/dat/leaderboard/" and lb.ranked == [("TheAvengers", 0.2532)]


def test_missing_leaderboard_page_means_no_leaderboard():
    # measured: DrivenData judged competitions (e.g. Pale Blue Dot) answer 404 on /leaderboard/
    with pytest.raises(NoLeaderboard, match="404"):
        fetch_leaderboard(make_fetcher({}), "drivendata", "https://www.drivendata.org/competitions/2/judged/")


def test_drivendata_page_without_the_partial_fails_loudly():
    f = make_fetcher({"GET https://www.drivendata.org/competitions/1/dat/leaderboard/": "<html>changed</html>"})
    with pytest.raises(LeaderboardError, match="leaderboard_partial"):
        fetch_leaderboard(f, "drivendata", "https://www.drivendata.org/competitions/1/dat/")


def test_other_fetch_errors_fail_the_item():
    import httpx
    f = make_fetcher({"GET https://www.aicrowd.com/challenges/x/leaderboards": httpx.Response(503)})
    with pytest.raises(LeaderboardError, match="503"):
        fetch_leaderboard(f, "aicrowd", "https://www.aicrowd.com/challenges/x")
