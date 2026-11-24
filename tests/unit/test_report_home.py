from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.operations.report_home import (current_root,
                                                            read_pointer)


def test_a_bad_pointer_is_ignored(tmp_path: Path):
    base = tmp_path / "reports"
    base.mkdir()
    (base / "current_campaign").write_text("../../etc/passwd")
    assert read_pointer(base) is None
    assert current_root(base / "live_campaign_1") == base / "live_campaign_1"


def test_the_benchmark_spec_pays_what_its_laws_cost():
    import json, sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.benchmark_campaign import DEFAULT_SPEC, lattice_spec
    spec = lattice_spec(json.loads(DEFAULT_SPEC.read_text()))
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.scheduling.limits import units_for_seconds
    least = units_for_seconds(spec, 4 * 3600)
    assert all(Policy.from_spec(spec).work_budget(n) >= least for n in Policy.from_spec(spec).ladder())


def test_the_shipped_survey_draws_only_n_independent_coefficients():
    import json
    from pathlib import Path
    from graph_scale_dynamics.scheduling.campaign import validate_campaign
    spec = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text())
    assert validate_campaign(spec) == []
    assert spec["search_policy"]["grid"]["scales"] == ["one"]
