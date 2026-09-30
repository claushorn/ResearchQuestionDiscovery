"""Code-side rules: scores follow what the earlier stages found; the recommendation is decided here."""
from opportunitygenerator.config import Thresholds
from opportunitygenerator.schema import OGOutput

NOVELTY_MAX = {"solved": 3, "partially_solved": 7}


def check(out: OGOutput, novelty: dict | None, ev: dict | None) -> None:
    """Raises ValueError (the output is rejected) when a score contradicts the earlier stages."""
    status = novelty["novelty"]["status"] if novelty else None
    if status in (None, "unclear"):
        if out.novelty_score is not None:
            raise ValueError(f"novelty_score must be null: novelty {'not checked' if status is None else 'unclear'}")
    elif out.novelty_score is None:
        raise ValueError(f"novelty_score missing although the novelty check found {status}")
    elif out.novelty_score > NOVELTY_MAX.get(status, 10):
        raise ValueError(f"novelty_score {out.novelty_score} > {NOVELTY_MAX[status]} for a {status} problem")
    if (ev is None) != (out.economic_value_score is None):
        raise ValueError("economic_value_score must be null exactly when economic value was not assessed")


def recommend(profile: dict, novelty_status: str | None, next_step: str, next_step_reason: str,
              t: Thresholds) -> tuple[str, str]:
    """`ignore` unless every known dimension reaches its threshold; otherwise the model's investigate / contact."""
    if novelty_status == "solved":
        return "ignore", "the novelty check found the problem solved"
    short = [f"{name} {profile[key]} < {limit}" for name, key, limit in (
        ("personal advantage", "personal_advantage", t.fit), ("tractability", "tractability", t.tractability),
        ("novelty", "novelty", t.novelty), ("economic value", "economic_value", t.value))
        if profile[key] is not None and profile[key] < limit]
    if short:
        return "ignore", "; ".join(short)
    return next_step, next_step_reason
