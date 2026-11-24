from __future__ import annotations

def test_the_runtime_can_tell_whether_the_table_is_git_tracked():
    from graph_scale_dynamics.calibration.table import durable_table_is_git_tracked

    assert durable_table_is_git_tracked() is False, (
        "this tree is not a git repository, so nothing can be tracked in it")
    assert durable_table_is_git_tracked("/nonexistent/path/xyz") is False
