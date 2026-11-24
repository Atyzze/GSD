from __future__ import annotations

import json

from graph_scale_dynamics.research import decision_engine_report as R
from graph_scale_dynamics.services.worker import cpu_speed as S


def _checkpoint(from_empty: int, given: int, **more) -> dict:
    return {"chains": [{"start": "empty", "attempted": {"add": from_empty - 5, "delete": 3, "swap": 2}},
                       {"start": "given", "attempted": {"add": given, "delete": 0, "swap": 0}},
                       *({"start": name, "attempted": attempted} for name, attempted in more.items())]}


def test_an_attempt_counts_only_the_moves_it_made():
    envelope = {"sampling_checkpoint": _checkpoint(3_000_000, 2_000_000)}
    resumed = {"checkpoint": _checkpoint(1_000_000, 0)}
    speed = S.cpu_speed(envelope, resumed, 20.0)
    assert speed["moves"] == 4_000_000 and speed["moves_per_cpu_second"] == 200_000.0
    assert S.cpu_speed(envelope, None, 25.0)["moves"] == 5_000_000
    assert S.cpu_speed(envelope, None, 0.0)["moves_per_cpu_second"] is None


def test_a_run_from_several_starts_counts_every_chain_s_moves():
    envelope = {"sampling_checkpoint": _checkpoint(3_000_000, 2_000_000,
                                                   honeycomb={"add": 1_000_000, "delete": 0, "swap": 0},
                                                   cubic={"add": 500_000, "delete": 500_000, "swap": 0})}
    assert S.chain_moves(envelope["sampling_checkpoint"]) == 7_000_000
    resumed = {"checkpoint": _checkpoint(1_000_000, 0, honeycomb={"add": 1_000_000, "delete": 0, "swap": 0})}
    assert S.cpu_speed(envelope, resumed, 50.0)["moves"] == 5_000_000


def test_the_cpu_it_ran_on_is_read_where_the_host_says():
    cpu = S.last_cpu()
    if cpu is not None:
        assert cpu >= 0
        speed = S.cpu_speed({"sampling_checkpoint": {}}, None, 1.0)
        assert speed["cpu"] is not None and speed["cpus_allowed"] >= 1


def test_the_seed_table_carries_it_and_reads_nothing_it_does_not_need():
    resource = {"pss_timeline": [1, 2, 3], "cpu_speed": {"moves_per_cpu_second": 181234.5, "cpu": 7, "l3": "0"}}
    assert R._speed_cells({"resource_json": json.dumps(resource)}) == (181234.5, 7, "0")
    assert R._speed_cells({"resource_json": json.dumps({"pss_timeline": []})}) == (None, None, None)
    assert R._speed_cells({}) == (None, None, None)
    at = R.SEED_COLUMNS.index("moves_per_cpu_second")
    assert R.SEED_COLUMNS[at:at + 3] == ("moves_per_cpu_second", "cpu", "die")
