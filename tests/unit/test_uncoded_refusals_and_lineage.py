import ast
from pathlib import Path

import pytest
from graph_scale_dynamics.scaleflow.flow import UNCODED_REFUSAL, _probe_refusal_counts

ROOT = Path(__file__).resolve().parents[2]
ESTIMATORS = ROOT / "graph_scale_dynamics/measurements/estimators.py"


def test_a_present_invalid_entry_with_no_code_is_counted_as_uncoded_and_decided_as_not_attempted():
    from graph_scale_dynamics.scaleflow.probes import Bucket, RefusalCode, bucket_for_rung
    counts = _probe_refusal_counts([{"d_s": {"valid": False}}, {"d_s": {"valid": False, "refusal": None}}])
    assert counts["d_s"] == {UNCODED_REFUSAL: 2}
    assert UNCODED_REFUSAL not in {code.value for code in RefusalCode}
    entry = {"valid": False, "refusal": UNCODED_REFUSAL}
    assert bucket_for_rung(entry, terminal_classification=None) is Bucket.NOT_ATTEMPTED


def test_a_chain_s_probe_with_no_number_reaches_the_summary_uncoded():
    from graph_scale_dynamics.decisions.every_chain import chain_metrics
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    metrics = {"chain_probes": {"square": {"d_s": {"valid": True, "value": None, "se": None, "refusal": None}}}}
    summary = rung_summary([chain_metrics(metrics, 1, "square")])
    assert summary["probe_refusals"]["d_s"] == {UNCODED_REFUSAL: 1}


def test_a_refused_entry_is_counted_by_its_code():
    counts = _probe_refusal_counts([{"d_s": {"valid": False, "refusal": "NOT_SETTLED"}}] * 2)
    assert counts["d_s"] == {"NOT_SETTLED": 2}


def test_an_absent_entry_is_not_measured_rather_than_uncoded():
    counts = _probe_refusal_counts([{}])
    assert counts["d_s"] == {"NOT_MEASURED": 1}
    assert counts["d_B"] == {"NOT_MEASURED": 1}


def test_a_valid_entry_contributes_no_refusal():
    counts = _probe_refusal_counts([{"d_s": {"valid": True, "d_s": 1.24}}])
    assert counts["d_s"] == {}


@pytest.mark.parametrize("channel,other", [("d_B", "d_w"), ("d_w", "d_B")])
def test_the_geometry_channels_never_emit_a_null_refusal(channel, other):
    tree = ast.parse(ESTIMATORS.read_text())
    dicts = [node for node in ast.walk(tree)
             if isinstance(node, ast.Dict)
             and any(isinstance(k, ast.Constant) and k.value == "refusal" for k in node.keys)]
    offenders = []
    for node in dicts:
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and key.value == "refusal"):
                continue
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) \
                    and value.func.attr == "get":
                offenders.append(ast.unparse(value))
    assert not offenders, (
        "an estimator writes `refusal` from a bare .get() with no fallback, so a "
        f"sub-estimator that succeeded records a null code: {offenders}")


def test_the_power_law_rejection_has_its_own_code():
    from graph_scale_dynamics.scaleflow.probes import RefusalCode
    assert RefusalCode.NOT_POWER_LAW.value == "NOT_POWER_LAW"


def test_the_new_code_does_not_widen_the_calibration_closure():
    from graph_scale_dynamics.calibration.fingerprint import measurement_closure
    assert set(measurement_closure()) == {
        "graph_scale_dynamics/measurements/box_covering.py",
        "graph_scale_dynamics/measurements/estimators.py",
        "graph_scale_dynamics/measurements/fits.py",
        "graph_scale_dynamics/measurements/walk_dimension.py",
    }
