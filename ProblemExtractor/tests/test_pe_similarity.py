from problemextractor.similarity import shortlist


def test_most_similar_first_unrelated_excluded_ties_by_id():
    docs = {"p3": "protein binder design for RBX1", "p1": "long horizon planning for warehouse robots",
            "p2": "robot planning under uncertainty with long horizons", "p4": "robot planning under uncertainty with long horizons"}
    got = shortlist("long-horizon robot planning under uncertainty", docs, k=5)
    assert got[:2] == ["p2", "p4"] and "p3" not in got and got[2] == "p1"


def test_empty_corpus_and_k():
    assert shortlist("anything", {}, k=5) == []
    assert len(shortlist("robot", {f"p{i}": "robot arm" for i in range(9)}, k=5)) == 5
