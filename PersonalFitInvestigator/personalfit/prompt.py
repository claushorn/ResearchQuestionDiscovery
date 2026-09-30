import json

from personalfit.profile import Profile, render

TASK = """<task>
You compare ONE technical problem with the profile of the person above and answer:
"If this person attacked this problem tomorrow, what advantage would they have over a random strong ML researcher?"

A strong ML researcher is the baseline: excellent at deep learning, reading papers, running experiments. Only count
what goes beyond that: domain knowledge, prior results on this or a closely related problem, data or compute access,
built systems, contacts, rare combinations of skills.

- advantages: each one a claim, the profile file it rests on (its path exactly as in <file path="...">) and a
  verbatim quote of at least 3 words copied character for character from THAT file, plus why a strong ML
  researcher lacks it. Self-ratings (capabilities.yaml) do not distinguish anyone from a strong ML researcher;
  prefer concrete evidence.
- gaps: what this person would be missing, and how to close each gap.
- interest_match: how well the problem matches the stated interests; interest_quote: the verbatim interest line
  (empty for none).
- personal_advantage: 0 (no edge over a strong ML researcher) to 10 (among the best-placed people in the world);
  reasoning; confidence: your probability that this assessment is right.
Be critical: most problems give no special advantage.
</task>"""


def system_prompt(profile: Profile) -> str:
    """The profile comes first and is identical on every call, so consecutive calls reuse the prompt cache."""
    return f"<profile>\n{render(profile)}\n</profile>\n\n{TASK}"


def render_input(problem: dict, novelty: dict | None, ev: dict | None) -> str:
    keys = ("problem", "current_state", "failure", "desired_capability", "why_it_matters")
    parts = ["<problem>\n" + json.dumps({k: problem.get(k) for k in keys}, ensure_ascii=False, default=str) + "\n</problem>"]
    if novelty:
        parts.append("<novelty>\n" + json.dumps({k: novelty.get(k) for k in ("novelty", "strongest_counterargument", "closest_work")},
                                                 ensure_ascii=False, default=str) + "\n</novelty>")
    if ev:
        parts.append("<economic_value>\n" + json.dumps(ev.get("economic_value"), ensure_ascii=False, default=str)
                     + "\n</economic_value>")
    return "\n".join(parts)
