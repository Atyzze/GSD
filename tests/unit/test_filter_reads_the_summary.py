from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text())


def test_a_cell_whose_population_tripled_is_not_reported_as_a_regression():
    import importlib.util
    module_spec = importlib.util.spec_from_file_location(
        "baseline_tool", ROOT / "tools" / "baseline.py")
    tool = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(tool)

    def cell(n, attempts, median):
        return {"n": n, "by_sweeps_multiplier": [{
            "sweeps_multiplier": 16.0, "attempts": attempts,
            "wall_distribution_seconds": {"median": median}}]}

    comparison = tool.compare_cost_by_n([cell(16384, 134, 9.29)],
                                        [cell(16384, 711, 53.90)])
    record = comparison["regressions"][0]
    ratio = record["candidate_attempts"] / record["baseline_attempts"]
    assert ratio >= tool.POPULATION_SHIFT_FACTOR, \
        "a 5.3x change in sample size is a different population, not a slower one"
