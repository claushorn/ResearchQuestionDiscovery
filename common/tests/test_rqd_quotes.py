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
