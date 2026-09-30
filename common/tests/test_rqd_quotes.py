from rqd.quotes import quote_in_text

TEXT = "The agency seeks methods for “long-horizon planning”, which remains an open challenge.\nAwards up to $1.5M."


def test_quote_in_text_normalises_quotes_and_whitespace():
    assert quote_in_text('for "long-horizon  planning", which', TEXT)
    assert not quote_in_text("the agency wants better planning", TEXT)
    assert not quote_in_text("", TEXT)
    assert quote_in_text("better forecasting.", "We need better\nforecasting\n.")
