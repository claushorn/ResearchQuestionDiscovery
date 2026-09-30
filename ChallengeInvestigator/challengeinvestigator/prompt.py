import json

BASELINE_PROMPT = """You look up ONE number: the organisers' baseline (benchmark) score of a finished challenge, on the metric of its final leaderboard (given below).

Look for the organisers' benchmark blog post, starter-kit README or challenge page (DrivenData publishes "benchmark" blog posts). baseline: that score on exactly this metric; leave it empty if you cannot find it. evidence: pages you opened with WebFetch, each with a verbatim sentence of at most 40 words copied character for character that states the score (never from a search snippet, no ellipses); evidence_index: the 1-based number of the entry that states it. Run at least {min_searches} WebSearch."""

INVESTIGATE_PROMPT = """You look for a way to BEAT the best solution of a finished challenge that still has headroom.

The final leaderboard (scraped) is given below: do not cite it as evidence; its scores need no quote.

1. solutions: find the best solutions (the winners' and top teams' code on GitHub/GitLab, write-ups, workshop or conference papers, winners posts on the challenge forum). For each: place, team, title, url, kind (code, writeup, paper, post), approach in two to four sentences, score only if a quote states it, and the number of the evidence entry that shows it.
2. ideas: propose at most 5 concrete ideas that could outperform the best solution. For each: the idea, what it builds on in the solutions found, why it could win (grounded in what the winners did or did not do), risks, effort (low, medium, high). Do not claim numeric gains; if you want to state an expected gain, put it in expected_gain_assumption, worded as an assumption.
3. summary: two to four sentences on where the remaining headroom is.

evidence: pages you opened with WebFetch, each with a verbatim quote of at most 40 words copied character for character (never from a search snippet, no ellipses). Numbers (scores, percentages) in your text must appear in an evidence quote. Run at least {min_searches} WebSearch."""


def render_challenge(item, headroom: dict | None = None) -> str:
    text = item.text[:12000]
    extra = "" if headroom is None else "\n<headroom>\n" + json.dumps(
        {k: headroom.get(k) for k in ("metric", "direction", "leaderboard", "winner", "ceiling", "baseline",
                                      "normalized_headroom", "verdict")}, default=str) + "\n</headroom>"
    return f"<challenge>\n<title>{item.title}</title>\n<url>{item.url}</url>\n<page>\n{text}\n</page>\n</challenge>{extra}"
