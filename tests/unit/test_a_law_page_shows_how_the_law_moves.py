from __future__ import annotations

from graph_scale_dynamics.services.api.law_dynamics import law_dynamics_of


def test_every_setting_of_the_dynamics_is_resolved_with_its_default_written_out():
    drawn = law_dynamics_of({"init": "empty", "dynamics": {
        "kind": "equilibrium", "beta": 0.184275, "locality": 0.887362, "sweeps": 33,
        "move_mix": {"add": 0.262707, "delete": 0.262707, "swap": 0.474586}}})
    assert drawn["locality"] == 0.887362 and abs(drawn["global_share"] - 0.112638) < 1e-12
    assert drawn["beta"] == 0.184275 and drawn["beta_used"] and abs(drawn["temperature"] - 1 / 0.184275) < 1e-12
    assert drawn["move_mix"] == {"add": 0.262707, "delete": 0.262707, "swap": 0.474586}
    assert drawn["sweeps"] == 33 and drawn["init"] == "empty" and drawn["regime"] == "equilibrium"
    plain = law_dynamics_of({"init": "empty", "dynamics": {"beta": 2.0, "sweeps": 30}})
    assert plain["locality"] == 0.0 and plain["global_share"] == 1.0 and plain["local_move"] == "toggle"
    assert plain["move_mix"] == {"add": 0.425, "delete": 0.425, "swap": 0.15}
    assert "locality" not in plain["written_in_the_spec"], "a locality at its default is not written in the spec"


def test_a_zero_temperature_law_says_its_beta_is_not_used():
    cold = law_dynamics_of({"dynamics": {"beta": 0.5, "zero_temperature": True, "sweeps": 30}})
    assert cold["regime"] == "zero_temperature" and cold["beta"] == 0.5
    assert cold["beta_used"] is False and cold["temperature"] is None
