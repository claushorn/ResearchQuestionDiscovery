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
    assert row_in_html("pranav_devarinti 19.369", TABLE)
    assert row_in_html("ACPL: 19.369 | Win Rate: 97.0%", TABLE)           # header words + one row's numbers
    assert not row_in_html("pranav_devarinti 23.495", TABLE)              # a neighbouring row's score
    assert not row_in_html("pranav_devarinti 19.37", TABLE)               # numbers must match exactly
    assert not row_in_html("pranav_devarinti", TABLE)                     # a row quote needs a number
    assert not row_in_html("champion 19.369", TABLE)                      # no quote word in the row or header
