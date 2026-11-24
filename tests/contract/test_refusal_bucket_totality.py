from __future__ import annotations

import pytest

from graph_scale_dynamics.scaleflow.probes import (
    Bucket, RefusalCode, UNBUCKETED_REFUSAL_CODES, _CODE_TO_BUCKET, bucket_for_rung,
)


def test_every_refusal_code_has_a_bucket():
    missing = sorted(code.value for code in set(RefusalCode) - set(_CODE_TO_BUCKET))
    assert not missing, (
        "these refusal codes resolve to no bucket, so `bucket_for_rung` raises "
        f"KeyError the first time an estimator writes one: {missing}. Add them to "
        "_CODE_TO_BUCKET in scaleflow/probes.py."
    )
    assert UNBUCKETED_REFUSAL_CODES == frozenset(), (
        "the exported set must agree with the map it is derived from")


def test_every_mapped_target_is_a_real_bucket():
    for code, bucket in _CODE_TO_BUCKET.items():
        assert isinstance(bucket, Bucket), f"{code} maps to {bucket!r}, which is not a Bucket"


def test_not_power_law_buckets_with_the_other_aicc_outcomes():
    assert _CODE_TO_BUCKET[RefusalCode.NOT_POWER_LAW] is Bucket.REFUSED_NO_SCALING_WINDOW
    assert (_CODE_TO_BUCKET[RefusalCode.NOT_POWER_LAW]
            is _CODE_TO_BUCKET[RefusalCode.EXPONENTIAL_GROWTH])


def test_bucket_for_rung_executes_on_every_code():
    for code in RefusalCode:
        entry = {"valid": False, "refusal": code.value, "reason": "fixture"}
        bucket = bucket_for_rung(entry, terminal_classification=None)
        assert isinstance(bucket, Bucket), f"{code.value} did not produce a Bucket"


def test_the_scorer_survives_a_refusal_code_on_a_rung():
    from graph_scale_dynamics.research.stability_score import score_rung_rows

    def row(n, refusal=None):
        summary = {p: {"valid": True, "mean": 1.0, "se": 0.01} for p in ("d_s", "d_V", "d_w")}
        if refusal:
            summary["d_B"] = {"valid": False}
            summary["probe_refusals"] = {"d_B": {refusal: 3}}
        else:
            summary["d_B"] = {"valid": True, "mean": 1.5, "se": 0.01}
        summary["connected_fraction"] = 1.0
        return {"n": n, "summary": summary,
                "terminal_classification": "EQUILIBRATED_ACTIVE", "chains_verdict": None}

    for code in RefusalCode:
        rows = [row(64, code.value), row(256, code.value),
                row(1024), row(4096), row(16384)]
        scored = score_rung_rows(rows, floors={}, floors_by_n={}, connectivity_floor=0.9)
        assert scored["buckets"]["d_B"] is not None, (
            f"scoring a block whose early rungs refused with {code.value} produced no bucket")


def test_an_unmapped_code_names_its_recovery():
    sentinel = RefusalCode.NOT_POWER_LAW
    saved = _CODE_TO_BUCKET.pop(sentinel)
    try:
        entry = {"valid": False, "refusal": sentinel.value, "reason": "fixture"}
        with pytest.raises(KeyError) as excinfo:
            bucket_for_rung(entry, terminal_classification=None)
        message = str(excinfo.value)
        assert "_CODE_TO_BUCKET" in message
        assert "scaleflow/probes.py" in message
    finally:
        _CODE_TO_BUCKET[sentinel] = saved
