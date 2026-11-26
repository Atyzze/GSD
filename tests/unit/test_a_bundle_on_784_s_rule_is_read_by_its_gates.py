from __future__ import annotations

import json

from graph_scale_dynamics.reporting import study_reading as R


def test_the_reading_says_every_gate_at_every_size_and_no_carried_ledger(tmp_path):
    (tmp_path / "study.json").write_text(json.dumps({"study_id": "169", "campaigns": [], "build_number": 813}))
    (tmp_path / "gates_ledger.json").write_text(json.dumps({
        "contract": "gsd-let-through-ledger-1", "from_n": 4096, "confirm_after": 100, "signatures_total": 2,
        "signatures": [{"signature": "ring", "n": 4096, "kept": 100, "read_one_size_up": 100, "seen_enough": True}],
        "gates": {"empty": {"256": {"let_through": 900, "clean": 880, "same_gate": 870, "missed": 3, "open": 17,
                                    "clean_since_last_miss": 400, "share": 1.0, "label": "records only"}}}}))
    reading = R.read_study(tmp_path)
    assert reading["gates_ledger"]["gates"]["empty"]["256"]["clean"] == 880 and "salt" not in reading
    assert "salt_ledger" not in reading["study"]
    text = R.render(reading)
    assert "every gate at every size, from this study's own decisions:" in text
    assert "empty: N=256 900 through, 880 clean (870), 3 missed, 17 open: records only" in text
    assert "known results: 1 of 2 signatures" in text and "the next new study's let-through" not in text
