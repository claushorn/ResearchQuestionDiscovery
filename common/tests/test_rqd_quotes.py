from rqd.quotes import quote_in_text

TEXT = "The agency seeks methods for “long-horizon planning”, which remains an open challenge.\nAwards up to $1.5M."


def test_quote_in_text_normalises_quotes_and_whitespace():
    assert quote_in_text('for "long-horizon  planning", which', TEXT)
    assert not quote_in_text("the agency wants better planning", TEXT)
    assert not quote_in_text("", TEXT)
    assert quote_in_text("better forecasting.", "We need better\nforecasting\n.")


def test_capitalised_first_word_of_a_mid_sentence_quote_matches():
    # measured 2026-09-30: model quoted "They still can't ..." where the page reads "... they still can't ..."
    assert quote_in_text("They still can't securely coordinate", "Agents are capable; they still can't securely coordinate.")


def test_terminal_punctuation_of_the_excerpt_is_ignored():
    # measured: "... while Greenoaks led the second." vs page "... led the second, Saban said."
    assert quote_in_text("Greenoaks led the second.", "while Greenoaks led the second, Saban said.")


def test_wording_must_still_match_exactly():
    assert not quote_in_text("Greenoaks led the first.", "while Greenoaks led the second, Saban said.")
    assert not quote_in_text("they cannot securely coordinate", "they still can't securely coordinate")


def test_quote_must_end_at_a_word_or_number_boundary():
    assert not quote_in_text("costs $40.", "the fix costs $400 per unit")
    assert quote_in_text("costs $400.", "the fix costs $400 per unit")


def test_markdown_emphasis_is_ignored():
    # measured: the agent quoted a README's markdown source "**log loss**"; the page renders "log loss"
    assert quote_in_text("The evaluation metric is **log loss**, which rewards", "The evaluation metric is log loss, which rewards")


TABLE = """<table><tr><th>#</th><th>Participants</th><th>ACPL</th><th>Win Rate (%)</th></tr>
<tr><td>01</td><td>pranav_devarinti</td><td>19.369</td><td>97.000</td></tr>
<tr><td>02</td><td>ivanchuks_fluffy_cat</td><td>23.495</td><td>90.000</td></tr></table>"""


def test_leaderboard_row_numbers_must_share_one_row():
    from rqd.quotes import row_in_html
    assert row_in_html("pranav_devarinti ACPL 19.369", TABLE)
    assert row_in_html("pranav_devarinti ACPL: 19.369 | Win Rate: 97.0%", TABLE)
    assert not row_in_html("pranav_devarinti ACPL 23.495", TABLE)         # a neighbouring row's score
    assert not row_in_html("pranav_devarinti ACPL 19.37", TABLE)          # numbers must match exactly
    assert not row_in_html("pranav_devarinti", TABLE)                     # a row quote needs a number
    assert not row_in_html("champion ACPL 19.369", TABLE)                 # a word neither in the row nor the header


LB = """<table><tr><th>#</th><th>Team</th><th>Score</th><th>Entries</th><th>Date</th></tr>
<tr><td>1</td><td>alpha_team</td><td>0.768</td><td>12</td><td>2024</td></tr>
<tr><td>2</td><td>beta_team</td><td>0.512</td><td>7</td><td>2023</td></tr>
<tr><td>9</td><td>gamma_team</td><td>0.301</td><td>3</td><td>2022</td></tr></table>"""


def test_row_quote_needs_the_rows_identity_and_no_invented_words():
    # review (critical): header words alone, or a fabricated sentence, verified any row's number
    from rqd.quotes import row_in_html
    assert not row_in_html("Team alpha_team reached a score of 0.301", LB)
    assert not row_in_html("the winning team scored 0.512", LB)
    assert not row_in_html("Team 0.301", LB)
    assert not row_in_html("Score 0.768", LB)                              # no team: which row?
    assert row_in_html("alpha_team Score 0.768", LB)


def test_row_quote_number_must_sit_in_the_named_column():
    # review: rank, entries and date columns backed a "score"
    from rqd.quotes import row_in_html
    assert not row_in_html("alpha_team 1", LB)                             # column not named
    assert not row_in_html("alpha_team Score 1", LB)                       # 1 is the rank, not the score
    assert not row_in_html("alpha_team Score 12", LB)                      # entries column
    assert not row_in_html("alpha_team Score 2024", LB)                    # date column
    assert row_in_html("alpha_team Entries 12", LB)


def test_nested_tables_do_not_merge_rows():
    from rqd.quotes import row_in_html
    nested = "<table><tr><td>" + LB + "</td></tr></table>"
    assert row_in_html("alpha_team Score 0.768", nested)
    assert not row_in_html("alpha_team Score 0.512", nested)               # beta_team's score
