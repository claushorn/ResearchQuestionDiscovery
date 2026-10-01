from problemextractor.state import PEState


def test_processed_candidates_are_remembered(tmp_path):
    st = PEState(tmp_path / "pe.db")
    assert not st.is_processed("cand-1")
    st.record("cand-1", "prob-1", "new", "2026-09-30T13:00:00+00:00")
    assert st.is_processed("cand-1") and PEState(tmp_path / "pe.db").is_processed("cand-1")


def test_all_maps_candidates_to_problem_and_decision(tmp_path):
    st = PEState(tmp_path / "pe.db")
    st.record("cand-1", "prob-1", "new", "2026-09-30T13:00:00+00:00")
    st.record("cand-2", "", "finished", "2026-09-30T13:00:00+00:00")
    assert st.all() == {"cand-1": ("prob-1", "new"), "cand-2": ("", "finished")}
