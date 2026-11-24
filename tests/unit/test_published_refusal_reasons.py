import re
from pathlib import Path

from graph_scale_dynamics.scaleflow.probes import RefusalCode
from graph_scale_dynamics.services.api.overview import _published_channels

ROOT = Path(__file__).resolve().parents[2]


def _summary(**overrides):
    base = {
        "d_s": None, "d_s_valid_fraction": 0.0,
        "d_V": {"mean": 1.8, "se": 0.05, "n_seeds": 3}, "d_V_valid_fraction": 1.0,
        "d_B": None, "d_B_valid_fraction": 0.0,
        "d_w": None, "d_w_valid_fraction": 0.0,
        "probe_refusals": {
            "d_s": {"NO_DIFFUSIVE_WINDOW": 3},
            "d_V": {},
            "d_B": {"NO_SCALING_WINDOW": 2, "UNPHYSICAL_FIT": 1},
            "d_w": {"REFUSED_MEAN_DEGREE_ABOVE_WINDOW": 3},
        },
    }
    base.update(overrides)
    return base


def _by_channel(rows):
    return {row["channel"]: row for row in rows}


def test_the_refusal_reason_is_published_next_to_the_missing_estimate():
    channels = _by_channel(_published_channels(_summary()))
    assert channels["d_s"]["mean"] is None
    assert channels["d_s"]["refusals"] == {"NO_DIFFUSIVE_WINDOW": 3}
    assert channels["d_w"]["refusals"] == {"REFUSED_MEAN_DEGREE_ABOVE_WINDOW": 3}


def test_a_probe_that_reported_carries_no_refusals():
    channels = _by_channel(_published_channels(_summary()))
    assert channels["d_V"]["mean"] == 1.8
    assert channels["d_V"]["refusals"] == {}


def test_seed_level_disagreement_survives_as_separate_codes():
    channels = _by_channel(_published_channels(_summary()))
    assert channels["d_B"]["refusals"] == {"NO_SCALING_WINDOW": 2, "UNPHYSICAL_FIT": 1}


def test_a_summary_without_refusals_degrades_to_the_old_behaviour():
    summary = _summary()
    del summary["probe_refusals"]
    channels = _by_channel(_published_channels(summary))
    assert channels["d_s"]["refusals"] == {}

    for junk in (None, [], "probe_refusals"):
        channels = _by_channel(_published_channels(_summary(probe_refusals=junk)))
        assert channels["d_s"]["refusals"] == {}


def test_the_payload_does_not_alias_the_stored_summary():
    summary = _summary()
    channels = _by_channel(_published_channels(summary))
    channels["d_s"]["refusals"]["INVENTED"] = 1
    assert summary["probe_refusals"]["d_s"] == {"NO_DIFFUSIVE_WINDOW": 3}


def test_every_code_the_estimators_can_emit_has_a_label_in_the_interface():
    codes = {code.value for code in RefusalCode}
    candidate = (ROOT / "graph_scale_dynamics/resources/ui/candidate.html").read_text()
    block = re.search(r"const REFUSAL_LABEL=\{(.*?)\n  \};", candidate, re.S)
    assert block, "REFUSAL_LABEL not found in the candidate page"
    labelled = set(re.findall(r"([A-Z_]+)\s*:", block.group(1)))

    missing = sorted(codes - labelled)
    assert not missing, f"RefusalCode(s) with no interface label: {missing}"
