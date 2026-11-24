from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / "graph_scale_dynamics" / "resources" / "calibration"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _margin_bands(path: Path) -> None:
    from graph_scale_dynamics.calibration import margins as M
    from graph_scale_dynamics.calibration import owed
    if owed.recalibration_owed() is not None:
        seed = _json(ROOT / "calibration" / "seed_table.json")
        assert _json(path)["source"]["estimator_fingerprint"] == seed["estimator_fingerprint"], (
            "while a recalibration is owed the bands are the seed's they were made from")
        return
    assert _json(path) == M.seed_bands(ROOT), "the seed moved: python3 tools/calibrate_margins.py --write"


def _finite_size(path: Path) -> None:
    from graph_scale_dynamics.calibration import finite_size as F
    document = _json(path)
    seed = _json(ROOT / "calibration" / "seed_table.json")
    assert document == F.committed() == F.measure(seed), "the seed moved: python3 tools/finite_size_tolerance.py --write"
    assert document["source"]["estimator_fingerprint"] == seed["estimator_fingerprint"], "fitted on the seed's cells"
    spec = _json(ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
    frozen = [tuple(row) for row in spec["engine"]["policy"]["finite_size_fits"]]
    assert frozen == [(name, fit["d_inf"], fit["a"], fit["omega"], fit["scatter"], fit["n_min"])
                      for name, fit in sorted(document["families"].items())], (
        "the shipped spec freezes these fits into a campaign: write the committed file's rows into "
        "engine.policy.finite_size_fits")
    assert spec["engine"]["policy"]["finite_size_scatter_sigmas"] == document["scatter_sigmas"]


def _recalibration_owed(path: Path) -> None:
    from graph_scale_dynamics.calibration import owed
    assert owed.recalibration_owed() is not None, "a declaration for another estimator, or a seed owing nothing"


def _structure(path: Path) -> None:
    from graph_scale_dynamics.measurements.structure_census import CENSUS_CONTRACT
    table = _json(path)
    assert table["census_contract"] == CENSUS_CONTRACT, "measured under another census: tools/calibrate_structure.py"
    assert table["computed_utc"] >= "2026-10-20", "measured before the instrument of 627"


def _operator_units(path: Path) -> None:
    from graph_scale_dynamics.services.proposer import blind
    units = _json(path)
    assert units["made_by"] == "tools/operator_units.py" and (ROOT / units["made_by"]).is_file()
    assert blind.operator_units()["units"] == units["units"], "the proposer reads exactly this table"


def _probe_windows(path: Path) -> None:
    from graph_scale_dynamics.calibration.fingerprint import estimator_fingerprint
    windows = _json(path)
    assert windows["source_estimator_fingerprint"] == estimator_fingerprint(), (
        "the probes moved since: python3 tools/selftest.py --build-windows --window-seeds 4")


def _table_rule(path: Path) -> None:
    rule = _json(path)
    assert rule["contract"] == "gsd-table-rule-2" and rule["committed_before"], "a rule says what it was committed before"
    for rests_on in (rule["rests_on"]["criterion"], rule["rests_on"]["judged"]):
        assert (ROOT / rests_on).is_file(), rests_on
    pinned = _json(ROOT / "tests" / "fixtures" / "committed_readings.json")["files"]
    assert path.relative_to(ROOT).as_posix() in pinned, "a rule is never edited after what it gives was computed"


def _table_holds(path: Path) -> None:
    from graph_scale_dynamics.calibration import rule
    assert _json(path) == rule.derive(), "not what the rule gives: python3 tools/table_rule.py --write"


def _score_margins(path: Path) -> None:
    from graph_scale_dynamics.research import score_known_answers as K
    assert _json(path) == K.run()[0], "not what the kept criterion's rule gives: python3 tools/score_known_answers.py --write"
    assert _json(path)["source"]["estimator_fingerprint"] == _json(ROOT / "calibration" / "seed_table.json")[
        "estimator_fingerprint"], "set on the seed's cells"


def _seed_table(path: Path) -> None:
    table = _json(path)
    for key in ("estimator_fingerprint", "science_fingerprint", "origin", "written_utc"):
        assert table.get(key), key


def _host_measured(path: Path) -> None:
    document = _json(path)
    assert document.get("source") and document.get("contract"), document.keys()


CHECKS = {
    RESOURCES / "d_s_margin_bands.json": _margin_bands,
    RESOURCES / "finite_size_tolerance.json": _finite_size,
    RESOURCES / "structure_thresholds.json": _structure,
    RESOURCES / "table_rule_2.json": _table_rule,
    RESOURCES / "table_holds.json": _table_holds,
    RESOURCES / "score_margins.json": _score_margins,
    RESOURCES / "operator_units.json": _operator_units,
    ROOT / "calibration" / "probe_windows.json": _probe_windows,
    ROOT / "calibration" / "seed_table.json": _seed_table,
    ROOT / "calibration" / "baselines" / "276-certified.json": _host_measured,
    **({ROOT / "calibration" / "recalibration_owed.json": _recalibration_owed}
       if (ROOT / "calibration" / "recalibration_owed.json").is_file() else {}),
}


def _committed() -> list[Path]:
    found = sorted(RESOURCES.rglob("*.json")) + sorted((ROOT / "calibration").rglob("*.json"))
    return [p for p in found if p.name != "probe_calibration.json"]


def test_every_derived_file_is_named_with_its_check():
    unnamed = [str(p.relative_to(ROOT)) for p in _committed() if p not in CHECKS]
    assert unnamed == [], f"a derived file with no check: add it to CHECKS with how it is held to its source: {unnamed}"


def test_every_derived_file_is_what_its_source_says():
    for path, check in CHECKS.items():
        assert path.is_file(), path
        check(path)


def test_a_recalibration_owed_is_declared_for_this_estimator_or_not_at_all():
    path = ROOT / "calibration" / "recalibration_owed.json"
    if path.is_file():
        _recalibration_owed(path)
    else:
        from graph_scale_dynamics.calibration import owed
        assert not owed.stale_cells(), "a seed with stale gate cells and no declaration"
