import pytest
import yaml

from fe_testing import fe_client, seed
from rqd.records import YamlStore


@pytest.fixture
def env(tmp_path):
    s = seed(tmp_path)
    s["client"] = fe_client(s["root"], raise_server_exceptions=False)
    return s


def get(env, url):
    res = env["client"].get(url)
    assert res.status_code == 200, res.text[:2000]
    assert "Traceback" not in res.text
    return res.text


def test_overview_shows_counts_per_stage(env):
    html = get(env, "/")
    for stage in ("Candidates", "Problems", "Novelty", "Economic value", "Fit", "Opportunities", "Challenges"):
        assert stage in html
    assert "waiting for extraction" in html


def test_candidates_page(env):
    html = get(env, "/candidates")
    c0, _, _, c3 = env["candidates"]
    assert c0 in html and "Synthetic problem statement 0." in html and 'href="/problems/prob-a"' in html
    assert 'name="ids" value="' + c3 + '"' in html and "due passed" in html
    assert 'value="extract"' in html  # next-stage action
    html = get(env, "/candidates?processed=no")
    assert c3 in html and c0 not in html


def test_problems_page_with_funnel_filters_and_paging(env):
    html = get(env, "/problems")
    assert "prob-a" in html and "OPP-0001" in html and "likely_open" in html and "$1.0M–$5.0M" in html
    for action in ("novelty", "economic_value", "fit", "generate"):
        assert f'value="{action}"' in html
    html = get(env, "/problems?fit_min=7")
    assert "/problems/prob-a" in html and "/problems/prob-b" not in html
    cfg = yaml.safe_load((env["root"] / "config.yaml").read_text())
    (env["root"] / "config.yaml").write_text(yaml.safe_dump(cfg | {"page_size": 1}))
    html = get(env, "/problems?sort=id&page=2")
    assert "/problems/prob-b" in html and "/problems/prob-a\"" not in html and "Page 2 of 3" in html
    assert "page=3" in html and "sort=id" in html  # the pager keeps the query


def test_bad_filter_value_is_a_clean_error(env):
    res = env["client"].get("/problems?fit_min=high")
    assert res.status_code == 500 and "fit_min" in res.text and "Fix:" in res.text and "Traceback" not in res.text


def test_dossier_in_pipeline_order_with_verification_badges(env):
    html = get(env, "/problems/prob-a")
    order = ["Sources", "Problem", "Novelty", "Economic value", "Fit", "Opportunity"]
    positions = [html.index(f"<h2>{h}") for h in order]
    assert positions == sorted(positions)
    assert "https://g.example/0" in html and "we leave this open" in html and "A lab may have solved it." in html
    assert "verified" in html and "unverified" in html and "notes.md" in html
    assert 'href="/opportunities/OPP-0001/brief"' in html and 'class="triage"' in html


def test_unknown_problem_is_a_clean_error_page(env):
    res = env["client"].get("/problems/prob-zzz")
    assert res.status_code == 500 and "no problem prob-zzz" in res.text and "Traceback" not in res.text


def test_opportunities_and_brief(env):
    html = get(env, "/opportunities")
    assert "OPP-0001" in html and "investigate" in html and "Can we solve prob-a?" in html
    html = get(env, "/opportunities/OPP-0001/brief")
    assert "Synthetic brief." in html


def test_challenges_and_detail(env):
    checked, unchecked = env["challenges"]
    html = get(env, "/challenges")
    assert "Challenge 0" in html and "open 40%" in html and "not checked" in html
    assert 'value="headroom"' in html and 'value="investigate"' in html
    html = get(env, f"/challenges/{checked}")
    assert "Accuracy" in html and "open" in html


def test_malformed_record_listed_on_the_page_while_others_show(env):
    (env["root"].parent / "ProblemExtractor" / "problems" / "prob-bad.yaml").write_text("x: [", encoding="utf-8")
    html = get(env, "/problems")
    assert "prob-bad.yaml" in html and "/problems/prob-a" in html and "Fix:" in html


def test_triage_controls_on_every_table(env):
    env["client"].post("/triage/problem/prob-a", data={"status": "shortlist", "note": ""})
    for url in ("/candidates", "/problems", "/opportunities", "/challenges"):
        assert 'class="triage"' in get(env, url)
    html = get(env, "/problems?triage=shortlist")
    assert "/problems/prob-a" in html and "/problems/prob-b" not in html


@pytest.mark.parametrize("content", ["x: [", "source_id: s\n"])  # not YAML / a candidate without its keys
def test_dossier_lists_an_unreadable_candidate_file_and_shows_the_rest(env, content):
    path = next((env["root"].parent / "SourceScout" / "output").glob(f"*/{env['candidates'][0]}.yaml"))
    path.write_text(content, encoding="utf-8")
    html = get(env, "/problems/prob-a")
    assert path.name in html and "Fix:" in html
    assert "Precise statement of prob-a." in html and "https://g.example/1" in html  # the other source still shows


def test_unreadable_challenge_record_is_a_clean_error_page(env):
    checked, _ = env["challenges"]
    (env["root"].parent / "ChallengeInvestigator" / "challenges" / f"{checked}.yaml").write_text("x: [", encoding="utf-8")
    res = env["client"].get(f"/challenges/{checked}")
    assert res.status_code == 500 and f"{checked}.yaml" in res.text and "Fix:" in res.text
    assert "Traceback" not in res.text and "Internal Server Error" not in res.text


def test_long_texts_are_clamped_in_tables_with_the_full_text_on_hover(env):
    """Full statements made Problems rows 10-15 lines tall (~3 of 498 rows per screen)."""
    assert '<span class="clamp" title="Precise statement of prob-a.">' in get(env, "/problems")
    assert '<span class="clamp" title="Synthetic problem statement 0.">' in get(env, "/candidates")
    assert '<span class="clamp" title="Can we solve prob-a?">' in get(env, "/opportunities")
    assert '<span class="clamp" title="Challenge 0">' in get(env, "/challenges")
    css = get(env, "/static/app.css")
    assert ".clamp" in css and "-webkit-line-clamp" in css
    assert "Precise statement of prob-a." in get(env, "/problems/prob-a")  # the dossier shows it in full


def test_payment_shows_its_type(env):
    """A bare `stated` hid the type: a company name (company_investment) looked like a payment."""
    assert "grant: $100k" in get(env, "/candidates") and "grant: $100k" in get(env, "/problems")
    assert "Payment: grant: $100k" in get(env, "/problems/prob-a")
