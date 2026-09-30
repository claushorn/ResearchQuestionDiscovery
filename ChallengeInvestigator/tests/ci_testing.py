"""Helpers for ChallengeInvestigator tests (unique module name: no conftest collisions)."""


def _aicrowd_row(rank, name, score, other="1.000"):
    return (f'<tr><td class="leaderboard-change"><img title="No change"></td><td><strong>{rank}</strong></td>'
            f'<td><span>{name}</span></td><td class="text-right"><strong>{score}</strong></td>'
            f'<td class="text-right">{other}</td></tr>')


def _aicrowd_baseline(name, score):
    return (f'<tr><td><span class="fa fa-thumb-tack" title="Baseline"></span></td><td></td>'
            f'<td class="participant"><div> Baseline <mark>{name}</mark> </div></td>'
            f'<td class="text-right"><strong>{score}</strong></td><td class="text-right">0.000</td></tr>')


def aicrowd_page(metric, rows, baselines=(), rounds=("Round 1", "Round 2"), track="Overall"):
    """Structure of an AIcrowd /leaderboards page (measured 2026-09-30): the primary score column is th.score-title,
    baseline rows carry title="Baseline", the round/track shown is an a.active link."""
    links = "".join(f'<a class="dropdown-item{" active" if r == rounds[-1] else ""}" '
                    f'href="/leaderboards?challenge_round_id={i}">{r}</a>' for i, r in enumerate(rounds))
    links += f'<a class="active" href="/leaderboards?challenge_leaderboard_extra_id=9">{track}</a>' if track else ""
    head = ('<tr><th class="leaderboard-change">Δ</th><th>#</th><th>Participants</th>'
            f'<th class="text-right score-title">{metric}</th><th class="text-right other-score-title">Other</th></tr>')
    body = "".join(_aicrowd_row(f"{i:02d}", n, s) for i, (n, s) in enumerate(rows, 1))
    body += "".join(_aicrowd_baseline(n, s) for n, s in baselines)
    return f"<html><body>{links}<table>{head}{body}</table></body></html>"


def drivendata_page(slug):
    return (f'<html><body><div hx-get="/competitions/1/{slug}/leaderboard_partial/?page=1" hx-trigger="load">'
            f'loading</div></body></html>')


def drivendata_partial(metric, rows, private=True):
    """Structure of a DrivenData leaderboard_partial fragment (measured 2026-09-30): rows carry data-rank, the primary
    column's header says "Best private" with the metric in span[title^="Metric:"]."""
    best = "Best private" if private else "Best public"
    head = ('<tr><th>Rank</th><th class="visually-hidden">Team members</th><th>Participant</th>'
            f'<th><div><span class="fw-normal"> {best} </span><br><span class="tooltip-underline" '
            f'title="Metric: {metric}">{metric}</span></div></th>'
            '<th><div><span class="tooltip-underline" title="Metric: AUROC">AUROC</span></div></th>'
            '<th>Shared work</th></tr>')
    body = "".join(f'<tr data-rank="{i}"><td><span class="fw-bold">#{i}</span></td><td></td>'
                   f'<td><div class="d-flex"><div class="fw-bold"><span>{n}</span></div></div>'
                   f'<div class="text-xs">2w ago ⸱ 20 submissions</div></td><td>{s}</td><td>0.9590</td><td></td></tr>'
                   for i, (n, s) in enumerate(rows, 1))
    return f"<table>{head}{body}</table>"


def baseline_output(value=0.6, quote="The benchmark model achieves a log loss of 0.6 on the test set", url="https://blog.example/bench"):
    ev = [{"title": "Benchmark", "url": url, "kind": "writeup", "quote": quote}]
    return {"evidence": ev, "baseline": value, "evidence_index": 1, "reasoning": "benchmark blog post"}


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
