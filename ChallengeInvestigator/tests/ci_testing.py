"""Helpers for ChallengeInvestigator tests (unique module name: no conftest collisions)."""


def evidence(*quotes):
    return [{"title": f"E{i}", "url": f"https://c.example/{i}", "kind": "leaderboard", "quote": q}
            for i, q in enumerate(quotes, 1)]


def val(quantity, value, basis="source", evidence=1, definition=""):
    return {"quantity": quantity, "value": value, "basis": basis, "evidence": evidence, "definition": definition}


def headroom_output(values, ev=None, direction="higher_is_better", **over):
    return {"metric": "accuracy", "direction": direction, "winner_team": "Team X",
            "evidence": ev if ev is not None else evidence("Team X scored 0.9 on the private leaderboard",
                                                           "the organisers' baseline reached 0.5 accuracy"),
            "values": values, "reasoning": "r", "confidence": 0.8} | over


def investigate_output(**over):
    base = {"evidence": [{"title": "Winner repo", "url": "https://c.example/repo", "kind": "repo",
                          "quote": "our 1st place solution scored 0.9 on the private leaderboard"},
                         {"title": "Rumour", "url": "https://c.example/rumour", "kind": "other",
                          "quote": "some team claims a big improvement"}],
            "solutions": [{"place": 1, "team": "Team X", "title": "1st place", "url": "https://c.example/repo",
                           "kind": "code", "approach": "ensemble of PPO agents", "score": 0.9, "evidence": 1},
                          {"place": 2, "team": "Team Y", "title": "2nd place", "url": "https://c.example/y",
                           "kind": "code", "approach": "self-play", "score": 0.88, "evidence": 2},
                          {"place": 3, "team": "Team Z", "title": "3rd place", "url": "https://c.example/z",
                           "kind": "writeup", "approach": "tuning", "score": None, "evidence": 5}],
            "ideas": [{"idea": "population-based training on top of the winner", "builds_on": "Team X ensemble",
                       "why_it_could_win": "the winner used a fixed population", "risks": "compute",
                       "effort": "medium", "expected_gain_assumption": "a few points if diversity was the bottleneck"},
                      {"idea": "distillation", "builds_on": "Team X", "why_it_could_win": "gains 12.5% over 0.9",
                       "risks": "none", "effort": "low", "expected_gain_assumption": ""}],
            "summary": "the winner scored 0.9"}
    return base | over
