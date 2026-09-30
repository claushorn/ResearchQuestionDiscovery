from datetime import date

from rqd.timeutil import deadline_summary

TODAY = date(2026, 9, 30)


def test_next_upcoming_deadline_and_all_passed():
    assert deadline_summary(["2026-07-10", "2026-12-01"], TODAY) == ("2026-12-01", False)
    assert deadline_summary(["2026-07-10"], TODAY) == (None, True)
    assert deadline_summary([], TODAY) == (None, False)
    assert deadline_summary(["2026-09-30"], TODAY) == ("2026-09-30", False)  # due today is not passed


def test_unparseable_deadlines_are_not_treated_as_passed():
    assert deadline_summary(["rolling", None, "2026-07-10"], TODAY) == (None, False)
