from ev_testing import problem
from economicvalue.prompt import render_input, system_prompt


def test_system_prompt_has_the_seven_questions_and_amount_rules():
    s = system_prompt(4)
    for q in ("Who has this problem", "How frequently", "How expensive", "What are they doing currently",
              "What does failure cost", "Could a solution be deployed", "Who controls the budget"):
        assert q in s
    assert "at least 4 WebSearch" in s and "only in estimates" in s and "unknown" in s


def test_input_contains_problem_score_and_novelty_findings():
    inv = {"novelty": {"status": "partially_solved"}, "strongest_counterargument": "standard security engineering",
           "closest_work": [{"title": "A2A protocol", "url": "https://a2a.example"}]}
    text = render_input(problem(), {"max_committed_usd": 250000.0, "salary_range_usd": None}, inv)
    assert "Plan long-horizon robot tasks" in text and "250000" in text
    assert "partially_solved" in text and "standard security engineering" in text and "A2A protocol" in text
    assert "not investigated" in render_input(problem(), {"max_committed_usd": None}, None)
