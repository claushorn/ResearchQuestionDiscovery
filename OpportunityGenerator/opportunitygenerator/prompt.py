import json

SYSTEM = """You turn what is known about ONE technical problem into an opportunity assessment for the person whose
personal fit is given. Scores are 0-10 judgments with reasoning; the earlier stages' findings are given, do not
contradict them.

- title_question: the problem as one short question of at most 12 words, e.g. "Can X be learned despite Y?".
- novelty_score: from the novelty check given (null if it is missing or its status is unclear; at most 3 if solved,
  at most 7 if partially solved). economic_value_score: from the economic value assessment given (null if missing).
- tractability_score: how likely a small team gets a meaningful first result within weeks (data, benchmarks,
  compute, evaluation available?); tractability_reasoning; tractability_confidence (0-1). Search for the data,
  benchmarks and compute a first experiment would need.
- asymmetric_upside (low, medium, high) with reasoning; likely engagement per channel (consulting, research,
  startup, employment: high, medium, low).
- why_unsolved; current_best_approach; what_we_could_test; first_experiment (concrete) with
  first_experiment_hours and first_experiment_compute_usd (your estimates, treated as assumptions);
  if_successful; if_failed (what it would still answer).
- thesis: two to four sentences, why this could be worth spending 10 hours investigating.
- next_step: investigate (a cheap experiment or analysis comes first) or contact (talking to a named organisation
  or buyer comes first), with next_step_reason.
- evidence: pages you opened with WebFetch, each with a verbatim quote of at most 40 words copied character for
  character (never from a search snippet). Numbers in your texts must appear in an evidence quote or the inputs.
Run at least {min_searches} WebSearch."""


def _block(tag: str, data) -> str:
    return f"<{tag}>\n{json.dumps(data, ensure_ascii=False, default=str)}\n</{tag}>"


def render_input(problem: dict, fit: dict, novelty: dict | None, ev: dict | None) -> str:
    keys = ("problem", "current_state", "failure", "desired_capability", "why_it_matters", "unsolvedness")
    parts = [_block("problem", {k: problem.get(k) for k in keys}),
             _block("personal_fit", {k: fit[k] for k in ("advantages", "gaps", "interest_match", "personal_advantage")})]
    parts.append(_block("novelty", {k: novelty.get(k) for k in ("novelty", "confidence", "strongest_counterargument",
                                                               "closest_work")}) if novelty
                 else "<novelty>not checked: novelty_score must be null</novelty>")
    parts.append(_block("economic_value", {"economic_value": ev.get("economic_value"), "confidence": ev.get("confidence")})
                 if ev else "<economic_value>not assessed: economic_value_score must be null</economic_value>")
    return "\n".join(parts)
