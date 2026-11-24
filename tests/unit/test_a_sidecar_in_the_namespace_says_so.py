from __future__ import annotations

from graph_scale_dynamics.operations import power_sidecar


def test_a_sidecar_started_inside_the_namespace_says_so_rather_than_looking_healthy():
    inside = {"btop_capabilities": ["cap_dac_read_search", "cap_perfmon"],
              "exec_inside_scratch_namespace": True,
              "rapl_readable_without_capability": False,
              "rapl_energy_path": str(power_sidecar.RAPL_ENERGY)}
    said = power_sidecar.why_no_watts(inside)
    assert said and "namespace" in said and "mapped" in said

    assert power_sidecar.why_no_watts(inside | {"exec_inside_scratch_namespace": False}) is None

    stripped = power_sidecar.why_no_watts(inside | {"btop_capabilities": []})
    assert stripped and "setcap" in stripped

    absent = power_sidecar.why_no_watts(inside | {"rapl_readable_without_capability": None})
    assert absent and "no RAPL" in absent

    assert power_sidecar.why_no_watts(inside | {"rapl_readable_without_capability": True}) is None
