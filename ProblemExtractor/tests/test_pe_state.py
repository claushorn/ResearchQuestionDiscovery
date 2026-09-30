from problemextractor.state import PEState


def test_processed_candidates_are_remembered(tmp_path):
    st = PEState(tmp_path / "pe.db")
    assert not st.is_processed("cand-1")
    st.record("cand-1", "prob-1", "new", "2026-09-30T13:00:00+00:00")
    assert st.is_processed("cand-1") and PEState(tmp_path / "pe.db").is_processed("cand-1")
