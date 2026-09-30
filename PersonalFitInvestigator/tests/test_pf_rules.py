from pf_testing import advantage, fit_output, make_profile
from personalfit.config import PFConfig
from personalfit.profile import load_profile
from personalfit.rules import apply
from personalfit.schema import FitOutput

RULES = {"self_rating_files": ["capabilities.yaml"], "self_rating_cap": 5, "no_advantage_cap": 2}


def run(tmp_path, **over):
    profile = load_profile(make_profile(tmp_path / "pp"), 10_000)
    return apply(FitOutput.model_validate(fit_output(**over)), profile, **RULES)


def test_verified_advantage_is_kept_with_profile_basis(tmp_path):
    r = run(tmp_path)
    assert r["advantages"][0]["basis"] == "profile" and r["personal_advantage"]["score"] == 9
    assert r["interest_match"] == {"level": "high", "quote": "sequential decision-making problems"} and r["warnings"] == []


def test_quote_must_be_in_the_cited_file(tmp_path):
    # the quote is in cv.md, but the model cites interests.yml
    r = run(tmp_path, advantages=[advantage(file="interests.yml")])
    assert r["advantages"] == [] and any("interests.yml" in w for w in r["warnings"])


def test_short_quote_or_unknown_file_is_dropped(tmp_path):
    r = run(tmp_path, advantages=[advantage(quote="ATLAS experiment"), advantage(file="nope.md")])
    assert r["advantages"] == [] and len(r["warnings"]) >= 2


def test_advantage_from_a_pdf_profile_file(tmp_path):
    r = run(tmp_path, advantages=[advantage(file="cv_long.pdf", quote="the data leakage problem in protein-ligand modeling")])
    assert len(r["advantages"]) == 1


def test_self_ratings_alone_cap_the_score(tmp_path):
    r = run(tmp_path, advantages=[advantage(file="capabilities.yaml", quote="reinforcement_learning: level: 9")])
    assert r["advantages"][0]["basis"] == "self_rating"
    assert r["personal_advantage"] == {"score": 5, "stated_by_model": 9, "reasoning": "founded the field's working group",
                                       "confidence": 0.8}
    assert any("self-rating" in w for w in r["warnings"])


def test_self_rating_plus_profile_evidence_is_not_capped(tmp_path):
    r = run(tmp_path, advantages=[advantage(file="capabilities.yaml", quote="reinforcement_learning: level: 9"), advantage()])
    assert r["personal_advantage"]["score"] == 9


def test_no_backed_advantage_caps_low(tmp_path):
    r = run(tmp_path, advantages=[advantage(quote="won the Nobel prize in 2013 alone")])
    assert r["personal_advantage"]["score"] == 2 and any("no advantage" in w for w in r["warnings"])
    assert run(tmp_path, advantages=[], personal_advantage=1)["personal_advantage"]["score"] == 1  # below cap: unchanged


def test_unverified_interest_quote_means_no_interest_match(tmp_path):
    r = run(tmp_path, interest_quote="quantum gravity phenomenology research")
    assert r["interest_match"] == {"level": "none", "quote": ""} and any("interest" in w for w in r["warnings"])


def test_config_ships_the_rule_values():
    from pathlib import Path
    from personalfit.config import load_config
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert isinstance(cfg, PFConfig) and cfg.self_rating_files == ["capabilities.yaml"] and cfg.agent.min_searches == 0


def test_a_two_word_interest_line_verifies_as_a_whole_line(tmp_path):
    r = run(tmp_path, interest_quote="protein engineering")
    assert r["interest_match"] == {"level": "high", "quote": "protein engineering"} and r["warnings"] == []
    r = run(tmp_path, interest_quote="protein")  # a fragment of a line is not an interest line
    assert r["interest_match"]["level"] == "none"
