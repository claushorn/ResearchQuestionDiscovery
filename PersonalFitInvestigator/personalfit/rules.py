"""Code-side rules: every advantage rests on a verbatim quote from the cited profile file; self-ratings alone, or
no backed advantage, cap the score."""
from personalfit.profile import Profile
from personalfit.schema import FitOutput
from rqd.quotes import quote_in_text
from rqd.verify import MIN_QUOTE_WORDS


def _in_file(profile: Profile, path: str, quote: str) -> str | None:
    """None if the quote is in that file, else why not."""
    f = profile.file(path)
    if f is None:
        return f"{path} is not a profile file"
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return f"quote shorter than {MIN_QUOTE_WORDS} words"
    return None if quote_in_text(quote, f.text) else f"quote not found in {path}"


def _is_line(profile: Profile, quote: str) -> bool:
    """An interest is a whole line of a profile file (interest lists are short: "protein engineering")."""
    return bool(quote.strip()) and any(quote_in_text(quote, line) and quote_in_text(line, quote)
                                       for f in profile.files for line in f.text.splitlines() if line.strip())


def apply(out: FitOutput, profile: Profile, *, self_rating_files: list[str], self_rating_cap: int,
          no_advantage_cap: int) -> dict:
    warnings, kept = [], []
    for a in out.advantages:
        why_not = _in_file(profile, a.file, a.quote)
        if why_not:
            warnings.append(f"advantage dropped ({a.claim[:60]}): {why_not}")
            continue
        kept.append(a.model_dump() | {"basis": "self_rating" if a.file in self_rating_files else "profile"})
    score = out.personal_advantage
    if not kept and score > no_advantage_cap:
        score = no_advantage_cap
        warnings.append(f"no advantage backed by a profile quote: score capped at {no_advantage_cap}")
    elif kept and all(a["basis"] == "self_rating" for a in kept) and score > self_rating_cap:
        score = self_rating_cap
        warnings.append(f"advantages rest only on self-ratings: score capped at {self_rating_cap}")
    interest = {"level": out.interest_match, "quote": out.interest_quote}
    if out.interest_match != "none" and not _is_line(profile, out.interest_quote):
        warnings.append("interest match dropped: its quote is not a line of a profile file")
        interest = {"level": "none", "quote": ""}
    return {"advantages": kept, "gaps": [g.model_dump() for g in out.gaps], "interest_match": interest,
            "personal_advantage": {"score": score, "stated_by_model": out.personal_advantage,
                                   "reasoning": out.reasoning, "confidence": out.confidence},
            "warnings": warnings}
