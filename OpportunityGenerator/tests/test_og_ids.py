from opportunitygenerator.ids import opp_id_for
from rqd.records import YamlStore


def test_ids_are_sequential_and_stable(tmp_path):
    store = YamlStore(tmp_path)
    assert opp_id_for(store, "prob-a") == "OPP-0001"
    store.save({"id": "OPP-0001", "problem_id": "prob-a"}, "OPP-0001")
    assert opp_id_for(store, "prob-a") == "OPP-0001"
    assert opp_id_for(store, "prob-b") == "OPP-0002"
    store.save({"id": "OPP-0007", "problem_id": "prob-c"}, "OPP-0007")
    assert opp_id_for(store, "prob-d") == "OPP-0008"
