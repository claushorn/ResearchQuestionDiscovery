import json

HEADROOM_PROMPT = """You check how much room is left to beat the best result of a FINISHED challenge.

Find, from the challenge page, its leaderboard and the winners announcement:
- metric: the primary metric used to rank the final (private) leaderboard; direction: higher_is_better or lower_is_better;
- winner: the top final score (winner_team: the team);
- ceiling: the best possible value of the metric. Either cite a page stating it (basis source), or, for a bounded metric, give the definition (basis definition, e.g. "accuracy is at most 1.0", "error cannot be below 0"). For unbounded metrics (rewards, scores without a maximum) give a ceiling only if a page states one;
- baseline: the organisers' baseline score, if published.

Every value with basis source must cite an evidence entry (1-based number) whose verbatim quote contains that exact number. evidence: pages you opened with WebFetch, with a verbatim quote of at most 40 words copied character for character (never from a search snippet, no ellipses). Run at least {min_searches} WebSearch. Leave out values you cannot back; do not compute the headroom yourself. confidence: your probability that the values are right."""

INVESTIGATE_PROMPT = """You look for a way to BEAT the best solution of a finished challenge that still has headroom.

1. solutions: find the best solutions (the winners' and top teams' code on GitHub/GitLab, write-ups, workshop or conference papers, winners posts on the challenge forum). For each: place, team, title, url, kind (code, writeup, paper, post), approach in two to four sentences, score only if a quote states it, and the number of the evidence entry that shows it.
2. ideas: propose at most 5 concrete ideas that could outperform the best solution. For each: the idea, what it builds on in the solutions found, why it could win (grounded in what the winners did or did not do), risks, effort (low, medium, high). Do not claim numeric gains; if you want to state an expected gain, put it in expected_gain_assumption, worded as an assumption.
3. summary: two to four sentences on where the remaining headroom is.

evidence: pages you opened with WebFetch, each with a verbatim quote of at most 40 words copied character for character (never from a search snippet, no ellipses). Numbers (scores, percentages) in your text must appear in an evidence quote. Run at least {min_searches} WebSearch."""


def render_challenge(item, headroom: dict | None = None) -> str:
    text = item.text[:12000]
    extra = "" if headroom is None else "\n<headroom>\n" + json.dumps(
        {k: headroom.get(k) for k in ("metric", "direction", "winner", "ceiling", "baseline", "normalized_headroom", "verdict")},
        default=str) + "\n</headroom>"
    return f"<challenge>\n<title>{item.title}</title>\n<url>{item.url}</url>\n<page>\n{text}\n</page>\n</challenge>{extra}"
