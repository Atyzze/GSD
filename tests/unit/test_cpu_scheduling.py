from graph_scale_dynamics.scheduling.cpu import choose_auto_slots, configured_monitor_ceiling


def test_auto_slots_use_smt_threads_with_logical_safety_cap():
    assert choose_auto_slots(physical=16, logical=32) == 32
    assert choose_auto_slots(physical=32, logical=64) == 32
    assert choose_auto_slots(physical=8, logical=16) == 16


def test_physical_only_mode_remains_available():
    assert choose_auto_slots(physical=16, logical=32, use_smt=False) == 16
    assert choose_auto_slots(physical=32, logical=64, use_smt=False) == 16
    assert choose_auto_slots(physical=8, logical=16, use_smt=False) == 8


def test_explicit_auto_override_can_use_smt_threads_but_not_exceed_host():
    assert choose_auto_slots(physical=16, logical=32, override=24) == 24
    assert choose_auto_slots(physical=16, logical=32, override=99) == 32
    assert choose_auto_slots(physical=16, logical=32, override=0) == 1


def test_cpu_meter_ceiling_is_expressed_against_logical_threads():
    assert configured_monitor_ceiling(8, 32) == 25.0
    assert configured_monitor_ceiling(16, 32) == 50.0
    assert configured_monitor_ceiling(32, 32) == 100.0
