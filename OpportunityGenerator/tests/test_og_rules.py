import pytest

from og_testing import ev, novelty, og_output
from opportunitygenerator.config import Thresholds
from opportunitygenerator.rules import check, recommend
from opportunitygenerator.schema import OGOutput

T = Thresholds(fit=7, tractability=5, novelty=5, value=4)


def out(**over):
    return OGOutput.model_validate(og_output(**over))


def test_scores_present_when_their_stage_ran():
    check(out(), novelty(), ev())


@pytest.mark.parametrize("ni, score, ok", [
    (None, None, True), (None, 6, False),
    ("unclear", None, True), ("unclear", 5, False),
    ("likely_open", None, False), ("likely_open", 9, True),
    ("solved", 3, True), ("solved", 4, False),
    ("partially_solved", 7, True), ("partially_solved", 8, False),
])
def test_novelty_score_follows_the_novelty_stage(ni, score, ok):
    o = out(novelty_score=score)
    n = novelty(status=ni) if ni else None
    if ok:
        check(o, n, ev())
    else:
        with pytest.raises(ValueError, match="novelty"):
            check(o, n, ev())


def test_value_score_null_exactly_when_ev_missing():
    check(out(economic_value_score=None), novelty(), None)
    with pytest.raises(ValueError, match="economic"):
        check(out(economic_value_score=5), novelty(), None)
    with pytest.raises(ValueError, match="economic"):
        check(out(economic_value_score=None), novelty(), ev())


def prof(**over):
    return {"novelty": 8, "economic_value": 7, "tractability": 6, "personal_advantage": 9} | over


@pytest.mark.parametrize("over, expected", [
    ({}, "investigate"),
    ({"personal_advantage": 7}, "investigate"), ({"personal_advantage": 6}, "ignore"),
    ({"tractability": 5}, "investigate"), ({"tractability": 4}, "ignore"),
    ({"novelty": 5}, "investigate"), ({"novelty": 4}, "ignore"),
    ({"economic_value": 4}, "investigate"), ({"economic_value": 3}, "ignore"),
    ({"novelty": None, "economic_value": None}, "investigate"),   # unknown does not block
])
def test_recommendation_thresholds(over, expected):
    assert recommend(prof(**over), "likely_open", "investigate", "r", T)[0] == expected


def test_solved_is_ignored_and_model_picks_among_eligible():
    rec, reason = recommend(prof(), "solved", "investigate", "r", T)
    assert rec == "ignore" and "solved" in reason
    assert recommend(prof(), None, "contact", "a named buyer", T) == ("contact", "a named buyer")
    rec, reason = recommend(prof(personal_advantage=3), None, "contact", "x", T)
    assert rec == "ignore" and "personal advantage 3 < 7" in reason
