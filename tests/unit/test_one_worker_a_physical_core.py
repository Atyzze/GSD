from __future__ import annotations

from graph_scale_dynamics.scheduling.concurrency import ramp_ceiling
from graph_scale_dynamics.scheduling.cpu import fleet_ceiling, held_slots, one_worker_a_core
from graph_scale_dynamics.services.api import fleet_snapshots as api_fleet_snapshots


def test_with_smt_the_fleet_stops_at_the_physical_cores():
    said = []
    assert one_worker_a_core(16, 32, say=said.append) == 16
    assert "16 at most" in said[-1] and "SMT on, 32 hardware threads" in said[-1]
    assert "operator" not in said[-1] and "20" not in said[-1].split("(")[0], "the rule is in the documents"
    assert one_worker_a_core(8, 8, say=said.append) == 8 and "no SMT" in said[-1], "a host without SMT uses every core"
    assert one_worker_a_core(64, 32, say=said.append) == 32, "never more than the threads there are"


def test_every_folder_gets_it_and_a_setting_of_its_own_wins():
    assert fleet_ceiling({}, 16, 32, say=lambda *_: None) == 16, "no folder kind is asked: every study"
    assert fleet_ceiling({"GSD_MAX_WORKERS": "24"}, 16, 32, say=lambda *_: None) == 24
    ceiling = ramp_ceiling(baseline=1, logical=32, override=fleet_ceiling({}, 16, 32, say=lambda *_: None))
    assert ceiling == 16, "the ramp grows to the cores and no further"


def test_an_explicit_worker_count_is_held_by_the_ramp_and_said_so():
    from graph_scale_dynamics.scheduling.concurrency import ramp_decision
    said = []
    assert held_slots(32, {}, say=said.append) == (32, 32)
    assert said[-1] == "compute slots: --workers 32 holds 32 slot(s); the ramp gives none back"
    assert "physical core" not in said[-1], "173's rerun printed the core rule though --workers 32 replaced it"
    assert held_slots(32, {"GSD_MAX_WORKERS": "40"}, say=said.append) == (32, 40) and "40 at most" in said[-1]
    assert held_slots(32, {"GSD_MAX_WORKERS": "8"}, say=lambda *_: None) == (32, 32)
    hot = ramp_decision(active=32, baseline=32, ceiling=32, host_cpu_percent=99.0,
                        available_bytes=60 * 1024 ** 3, floor_bytes=10 * 1024 ** 3, connection_headroom=40,
                        runnable=200, seconds_since_step=60.0, launch_allowed=True, launch_reasons=())
    assert hot.slots == 32, "at 99% CPU the ramp gives nothing back below a held count (173's rerun fell to 23)"
    auto = ramp_decision(active=32, baseline=1, ceiling=32, host_cpu_percent=99.0,
                         available_bytes=60 * 1024 ** 3, floor_bytes=10 * 1024 ** 3, connection_headroom=40,
                         runnable=200, seconds_since_step=60.0, launch_allowed=True, launch_reasons=())
    assert auto.slots < 32, "the ramp's own floor gives back above its target"


def test_the_system_page_names_it_in_every_folder():
    assert api_fleet_snapshots._one_worker_per_core(None, 16, 16, 32) == {"physical": 16, "logical": 32}
    assert api_fleet_snapshots._one_worker_per_core(None, 24, 16, 32) is None, "slots past the cores are not this rule"
    assert api_fleet_snapshots._one_worker_per_core(None, 8, 8, 8) is None, "no SMT, nothing left free"
