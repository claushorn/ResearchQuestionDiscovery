from rqd.cli import hold_lock, lock_held


def test_lock_held_sees_a_running_command_without_taking_or_creating_the_lock(tmp_path):
    assert lock_held(tmp_path) is False and not (tmp_path / "data").exists()  # nothing created
    with hold_lock(tmp_path):
        assert lock_held(tmp_path) is True
    assert lock_held(tmp_path) is False
    with hold_lock(tmp_path):  # the probe released it again
        pass
