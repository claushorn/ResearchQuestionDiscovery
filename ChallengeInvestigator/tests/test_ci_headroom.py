import pytest

from ci_testing import evidence, headroom_output, val
from challengeinvestigator.headroom import compute
from challengeinvestigator.schema import HEADROOM_SCHEMA, HeadroomOutput

CEIL = val("ceiling", 1.0, basis="definition", evidence=0, definition="accuracy is at most 1.0")


def c(values, ev=None, verification=None, threshold=0.10, **over):
    out = HeadroomOutput.model_validate(headroom_output(values, ev, **over))
    return compute(out, verification or ["verified"] * len(out.evidence), threshold)


def test_schema_is_flat():
    assert not [k for k, v in HEADROOM_SCHEMA["properties"].items() if v.get("type") == "object" or "$ref" in v]


def test_headroom_with_baseline():
    h = c([val("winner", 0.9), CEIL, val("baseline", 0.5, evidence=2)])
    assert h["normalized_headroom"] == pytest.approx(0.2) and h["verdict"] == "headroom"
    assert h["winner"]["team"] == "Team X" and h["ceiling"]["basis"][0]["type"] == "definition"


def test_solved_when_gap_below_threshold():
    ev = evidence("winner reached 0.97 accuracy overall", "the baseline got 0.62 accuracy")
    h = c([val("winner", 0.97), CEIL, val("baseline", 0.62, evidence=2)], ev=ev)
    assert h["normalized_headroom"] == pytest.approx(0.03 / 0.38) and h["verdict"] == "solved"


def test_without_baseline_gap_relative_to_ceiling():
    ev = evidence("winner reached 0.95 accuracy overall")
    h = c([val("winner", 0.95), CEIL], ev=ev)
    assert h["normalized_headroom"] == pytest.approx(0.05) and h["verdict"] == "solved"


def test_threshold_edge_counts_as_headroom():
    ev = evidence("winner reached 0.9 accuracy overall")
    assert c([val("winner", 0.9), CEIL], ev=ev)["verdict"] == "headroom"  # exactly 10% left


def test_winner_not_in_quote_is_unclear_never_solved():
    h = c([val("winner", 0.99), CEIL])
    assert h["verdict"] == "unclear" and any("winner" in w for w in h["warnings"])


def test_ceiling_needs_source_or_stated_definition():
    assert c([val("winner", 0.9), val("ceiling", 1.0, basis="definition", evidence=0)])["verdict"] == "unclear"
    assert c([val("winner", 0.9), val("ceiling", 1.0, evidence=1)])["verdict"] == "unclear"  # 1.0 not in quote


def test_definition_basis_not_allowed_for_winner():
    h = c([val("winner", 0.9, basis="definition", evidence=0, definition="trust me"), CEIL])
    assert h["verdict"] == "unclear"


def test_best_of_several_backed_winner_rows():
    ev = evidence("Team X scored 0.9 on the private leaderboard", "Team Y scored 0.92 on the private leaderboard")
    h = c([val("winner", 0.9), val("winner", 0.92, evidence=2), CEIL], ev=ev)
    assert h["winner"]["value"] == 0.92


def test_percent_quotes_match_fraction_or_percent_values():
    ev = evidence("the winning entry reached 87.1% accuracy")
    assert c([val("winner", 0.871), CEIL], ev=ev)["winner"]["value"] == 0.871
    assert c([val("winner", 87.1), val("ceiling", 100, basis="definition", evidence=0, definition="max 100%")], ev=ev)["winner"]


def test_lower_is_better_with_and_without_baseline():
    ev = evidence("the winner's error was 0.2 on the test set", "the baseline error was 0.5 on the test set")
    zero = val("ceiling", 0.0, basis="definition", evidence=0, definition="error cannot be below 0")
    h = c([val("winner", 0.2), zero, val("baseline", 0.5, evidence=2)], ev=ev, direction="lower_is_better")
    assert h["normalized_headroom"] == pytest.approx(0.4) and h["verdict"] == "headroom"
    h = c([val("winner", 0.2), zero], ev=ev, direction="lower_is_better")
    assert h["verdict"] == "unclear" and any("baseline" in w for w in h["warnings"])


def test_winner_beyond_ceiling_is_unclear():
    ev = evidence("the winner scored 1.2 on the benchmark")
    assert c([val("winner", 1.2), CEIL], ev=ev)["verdict"] == "unclear"


def test_unverified_evidence_does_not_back_a_value():
    assert c([val("winner", 0.9), CEIL], verification=["quote_not_found", "verified"])["verdict"] == "unclear"
