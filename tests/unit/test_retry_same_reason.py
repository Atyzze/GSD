from __future__ import annotations

from graph_scale_dynamics.observability.child_diagnostics import (
    SAME_REASON_STOP, failure_class, same_reason_exhausted,
)


def test_every_failure_has_a_class_and_unknown_is_a_class():
    assert failure_class({}) == "unknown"
    assert failure_class({"classification": "signal_termination", "signal_name": "SIGKILL"}) == "oom_killed"
    assert failure_class({"classification": "signal_termination", "signal_name": "SIGSEGV"}) == "signal:SIGSEGV"
    assert failure_class({"classification": "python_exception",
                          "terminal_receipt": {"exception_type": "ValueError"}}) == "exception:ValueError"
    assert failure_class({"classification": "python_exception",
                          "terminal_receipt": {"exception_type": "MemoryError"}}) == "oom_python"
    assert failure_class({"classification": "missing_failure_receipt"}) == "no_result"


def test_third_same_reason_stops_but_mixed_reasons_continue():
    assert SAME_REASON_STOP == 3
    assert same_reason_exhausted(["oom_killed", "unknown", "oom_killed"]) is None
    assert same_reason_exhausted(["oom_killed", "unknown", "oom_killed", "oom_killed"]) == "oom_killed"
    assert same_reason_exhausted(["a", "b", "c", "d", "e", "f"]) is None
    assert same_reason_exhausted(["unknown"] * 3) == "unknown"
