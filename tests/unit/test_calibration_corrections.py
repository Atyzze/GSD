from __future__ import annotations

def test_the_spectral_probe_is_fooled_across_the_whole_search_window():
    from graph_scale_dynamics.measurements.calibration import (
        SPECTRAL_BRANCHING_LINE_BAND, SPECTRAL_FALSE_CONFIDENCE_BAND)

    low, high = SPECTRAL_FALSE_CONFIDENCE_BAND
    assert high >= 8.0, (
        "the false-confidence band must cover the campaign's whole mean-degree "
        "window; claiming an edge the table does not show is how build 351 got "
        "this wrong the first time")
    assert SPECTRAL_BRANCHING_LINE_BAND[1] < high, (
        "the branching line has an upper edge and the false confidence does not; "
        "collapsing the two is the error")


def test_the_crt_bias_is_recorded_per_channel_and_not_averaged_away():
    from graph_scale_dynamics.measurements.calibration import CRT_MEASURED_BIAS

    assert abs(CRT_MEASURED_BIAS["d_s"]["bias"]) < 0.10
    assert CRT_MEASURED_BIAS["d_s"]["shrinks_with_n"] is True
    for channel in ("d_B", "d_w"):
        entry = CRT_MEASURED_BIAS[channel]
        assert abs(entry["bias"]) > 0.35, f"{channel}'s bias on the CRT is large"
        assert entry["shrinks_with_n"] is False, (
            f"{channel} does not converge on this family; more N does not buy it back")


def test_the_tree_is_held_by_the_one_probe_the_judged_set_held_it_by():
    from graph_scale_dynamics.measurements.calibration import ladder_tolerance

    for channel in ("d_V", "d_w", "d_B"):
        for n in (256, 4096, 262144):
            assert ladder_tolerance("uniform_random_tree", channel, n) is None, (
                f"{channel} does not reach the tree's exact value at any size the table has: measured and shown")
    assert ladder_tolerance("uniform_random_tree", "d_s", 1024) is None, "under the size a verdict is relied on"
    assert ladder_tolerance("uniform_random_tree", "d_s", 4096) == 0.2
    assert ladder_tolerance("uniform_random_tree", "d_s", 1048576) == 0.2, "the band of the largest size judged"


def test_a_tolerance_or_gating_edit_never_invalidates_a_cell(tmp_path):
    import ast

    from graph_scale_dynamics.calibration import fingerprint as FP
    from graph_scale_dynamics.calibration.contract import SUITE_FAMILIES

    source = (FP.repository_root() / FP.FAMILY_SOURCE).read_text(encoding="utf-8")
    judging = {"theory", "ladder", "expectation", "why", "refusal_gated_from"}
    assert not judging & set(FP.FAMILY_MEASUREMENT_KEYS)
    families = FP._family_dicts(ast.parse(source))
    edited = 0
    for name in SUITE_FAMILIES:
        for key, value in zip(families[name].keys, families[name].values, strict=True):
            if isinstance(key, ast.Constant) and key.value in judging:
                lines = source.splitlines(keepends=True)
                start = sum(map(len, lines[:value.lineno - 1])) + value.col_offset
                end = sum(map(len, lines[:value.end_lineno - 1])) + value.end_col_offset
                changed = tmp_path / f"{name}_{key.value}.py"
                changed.write_text(source[:start] + "None" + source[end:], encoding="utf-8")
                assert FP.family_slice_source(name, changed) == FP.family_slice_source(name), (name, key.value)
                edited += 1
    assert edited, "no family declares a key that judges or plans its cells"
    FP.clear_caches()
    first = {family: FP.cell_fingerprint(family) for family in SUITE_FAMILIES}
    FP.clear_caches()
    assert {family: FP.cell_fingerprint(family) for family in SUITE_FAMILIES} == first


    FP.clear_caches()
    first = {family: FP.cell_fingerprint(family) for family in SUITE_FAMILIES}
    FP.clear_caches()
    assert {family: FP.cell_fingerprint(family) for family in SUITE_FAMILIES} == first


def test_the_suite_key_does_not_move_when_only_verdicts_change():
    from graph_scale_dynamics.calibration.cells import suite_families
    from graph_scale_dynamics.calibration.contract import AUTHORITATIVE_SEEDS
    from graph_scale_dynamics.calibration.table import suite_fingerprint

    families = suite_families()
    key = suite_fingerprint(families, seeds=AUTHORITATIVE_SEEDS)
    assert key == suite_fingerprint(families, seeds=AUTHORITATIVE_SEEDS)
    assert suite_fingerprint(families, seeds=AUTHORITATIVE_SEEDS + 1) != key, (
        "seed count is part of the plan and must move the key")
