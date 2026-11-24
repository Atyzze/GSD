from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import calibrate_structure as calibration  # noqa: E402
from graph_scale_dynamics.measurements.structure_census import CENSUS_CONTRACT  # noqa: E402
from graph_scale_dynamics.research import structure_reading as SR  # noqa: E402
from graph_scale_dynamics.research.what_happened import law_story, motion  # noqa: E402

TABLE = json.loads(calibration.TABLE.read_text(encoding="utf-8"))


def test_the_table_is_committed_for_the_census_in_force():
    assert TABLE["contract"] == calibration.CONTRACT
    assert TABLE["census_contract"] == CENSUS_CONTRACT, (
        "the census changed: run `uv run python tools/calibrate_structure.py` again")
    assert len(TABLE["families"]) == 15


def test_the_thresholds_reproduce_from_the_stored_rows_and_separate_every_family():
    thresholds = calibration.thresholds(calibration.exponents(TABLE["rows"]))
    assert thresholds["gap_exponent_at_most"] == TABLE["thresholds"]["gap_exponent_at_most"]
    assert thresholds["diameter_exponent_at_least"] == TABLE["thresholds"]["diameter_exponent_at_least"]
    assert thresholds["all_classified_right"]


def test_the_lattices_read_their_theory():
    for name, d in (("periodic_ring", 1), ("periodic_square_lattice", 2), ("periodic_cubic_lattice", 3),
                    ("periodic_hypercubic_lattice_4d", 4)):
        family = TABLE["families"][name]
        assert abs(family["gap_exponent"] + 2.0 / d) < 0.05, (name, family["gap_exponent"])
        assert abs(family["diameter_exponent"] - 1.0 / d) < 0.02, (name, family["diameter_exponent"])


def test_the_reader_classifies_every_family_as_the_committed_rule_does():
    for name, family in TABLE["families"].items():
        rows = [r for r in TABLE["rows"] if r["family"] == name]
        by_n: dict[int, list] = {}
        for r in rows:
            by_n.setdefault(r["n"], []).append(r)
        rungs = [{"n": n, "spectral_gap": {"mean": _mean([r["gap"] for r in rs])},
                  "diameter": {"mean": _mean([r["diameter"] for r in rs])}} for n, rs in sorted(by_n.items())]
        verdict = SR.verdict(rungs)
        assert verdict["finite_dimension"] is family["finite_dimension"], (name, verdict["why"])


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def test_the_configuration_model_gives_the_poisson_giant():
    poisson = {k: math.exp(-2.5) * 2.5 ** k / math.factorial(k) for k in range(40)}
    assert abs(SR.configuration_giant_fraction(poisson) - 0.8926) < 1e-3
    assert SR.configuration_giant_fraction({1: 0.5, 2: 0.5}) == 0.0, "no giant below Molloy-Reed zero"


def _seed(n, hist, giant, gap, diameter, *, accounting=None, failures=(), structural=None):
    return {"n": n, "seed": 0, "metrics": {
        "census": {"empty": {"degree_histogram": hist,
                               "largest_component": {"size": giant, "cycle_rank": 5,
                                                     "spectral_gap": {"value": gap},
                                                     "diameter": {"lower_bound": diameter}}},
                   "given": {"degree_histogram": hist, "components": {"count": 2},
                               "largest_component": {"size": giant - 3, "cycle_rank": 5,
                                                     "spectral_gap": {"value": gap},
                                                     "diameter": {"lower_bound": diameter + 1}}}},
        "health": {"rung_terminal": {"reason": "ceiling", "classification": "METASTABLE_OR_NONMIXING"},
                   "sampling_checkpoints": [{"multiplier": 64, "failures": [{"code": c} for c in failures],
                                             "certificate": {"effective_samples": 3.0, "split": {"energy": 4.2},
                                                             "structural_split": structural or {},
                                                             "structural_limits": {"connected_fraction": 0.25},
                                                             "stationarity_drift": 0.1}}]},
        "move_accounting": {"empty": accounting, "given": accounting},
        "d_s": {"valid": False, "refusal": "NO_DIFFUSIVE_WINDOW"}}}


def test_a_law_reads_its_degrees_its_giant_against_random_and_the_rule():
    hist = {"1": 10, "2": 40, "3": 50}
    rows = [_seed(n, hist, int(0.9 * n), 4.0 / n, int(n ** 0.5)) for n in (4096, 16384, 65536)]
    reading = SR.law_structure(rows)
    top = reading["rungs"][-1]
    assert abs(top["p2"]["mean"] - 0.4) < 1e-12 and abs(top["p3_plus"]["mean"] - 0.5) < 1e-12
    assert abs(top["molloy_reed"]["mean"] - (0.1 * -1 + 0.5 * 3)) < 1e-12
    assert top["giant_excess"] == round(0.9 - top["predicted_giant_fraction"]["mean"], 4)
    assert reading["finite_dimension"] is True and abs(reading["implied_spectral_dimension"] - 2.0) < 0.05


def test_what_happened_says_every_clause_with_its_numbers():
    late = {"counts": {"add.local.neg.accepted": 10, "add.local.zero.accepted": 180,
                       "delete.local.pos.accepted": 10, "add.local.pos.rejected": 800}}
    rows = [_seed(1024, {"3": 1}, 1000, 0.01, 12, accounting={"late": late, "last_decrease_move": 90},
                  failures=("EFFECTIVE_SAMPLES_BELOW_TARGET", "STARTS_DISAGREED"),
                  structural={"connected_fraction": 0.3})]
    story = law_story(rows, {"action": "hold", "rule": "unsettled", "at_n": 1024, "reason": "d_s moved"})
    text = {c["topic"]: c["text"] for c in story["clauses"]}
    assert story["rung"] == 1024
    assert "METASTABLE_OR_NONMIXING" in text["how the seeds ended"]
    assert "EFFECTIVE_SAMPLES_BELOW_TARGET on 1 of 1" in text["the certificate on the last chunk"]
    assert "connected fraction gap up to 0.300 against 0.25" in text["the certificate on the last chunk"]
    assert "wandering on a plateau" in text["how the chains from the empty start moved"]
    assert "empty giant 0.977" in text["every chain's final graph"]
    assert "given giant 0.974" in text["every chain's final graph"], "each chain's own, none against another's"
    assert "(the target not recorded)" in text["the certificate on the last chunk"], (
        "what the policy asked, from the seed's own record, never a number typed into the story")
    assert "how the chains from the given start came to rest" in text
    assert "d_s: NO_DIFFUSIVE_WINDOW" in text["the probes"]
    assert motion({"late": {"counts": {}}}) is None


def test_what_happened_reads_every_given_chain_by_its_start_s_name():
    late = {"counts": {"add.local.zero.accepted": 9, "add.local.neg.accepted": 1}}
    frozen = {"late": {"counts": {"add.local.zero.rejected": 50}}}
    row = _seed(4096, {"3": 1}, 4000, 0.01, 40, accounting={"late": late, "last_decrease_move": 90})
    metrics = row["metrics"]
    cubic = json.loads(json.dumps(metrics["census"]["given"]))
    cubic["largest_component"]["size"] = 4096
    metrics["census"]["more_given"] = {"honeycomb": None, "cubic": cubic}
    metrics["move_accounting"]["more_given"] = {"honeycomb": frozen, "cubic": {"late": late}}
    metrics["health"]["rung_terminal"]["given_chains"] = [{"name": "random"}, {"name": "honeycomb"}, {"name": "cubic"}]
    text = {c["topic"]: c["text"] for c in law_story([row])["clauses"]}
    assert "wandering on a plateau" in text["how the chains from the random start moved"]
    assert text["how the chains from the honeycomb start moved"].startswith("seed 0: no move was accepted")
    assert "wandering on a plateau" in text["how the chains from the cubic start moved"]
    assert "how the chains from the given start moved" not in text
    graphs = text["every chain's final graph"]
    assert "random giant 0.976" in graphs and "cubic giant 1.000" in graphs
    assert "honeycomb giant" not in graphs, "a chain with no census has no final graph to say"
    assert "how the chains from the random start came to rest" in text, "every chain's rest, by its start's name"


def test_the_preview_artefacts_are_not_decidable():
    def rung(n, gap, diameter, giant):
        return {"n": n, "spectral_gap": {"mean": gap}, "diameter": {"mean": diameter},
                "measured_giant_fraction": {"mean": giant}}
    tiny = SR.verdict([rung(4096, 1e-3, 30, 0.001), rung(16384, 1e-4, 90, 0.001)])
    assert tiny["finite_dimension"] is None and "giant component" in tiny["why"]
    jump = SR.verdict([rung(4096, 1e-2, 10, 1.0), rung(16384, 5e-6, 350, 0.95)])
    assert jump["finite_dimension"] is None and "structure changed" in jump["why"]
    grown = SR.verdict([rung(4096, 4.0 / 2048, 2048 ** 0.5, 0.5), rung(16384, 4.0 / 16384, 16384 ** 0.5, 1.0)])
    assert grown["finite_dimension"] is True and abs(grown["implied_spectral_dimension"] - 2.0) < 1e-6


def test_the_preview_reads_the_given_chain_too_and_counts_where_the_two_chains_part():
    from graph_scale_dynamics.research.record_report import _structure

    hist = {"2": 40, "3": 60}

    def law(candidate, *, given_is_an_expander):
        rows = []
        for n in (4096, 16384, 65536, 262144):
            row = _seed(n, hist, n, 4.0 / n, int(n ** 0.5))
            if given_is_an_expander:
                given = row["metrics"]["census"]["given"]["largest_component"]
                given["spectral_gap"] = {"value": 0.2}
                given["diameter"] = {"lower_bound": int(3 * math.log(n))}
            rows.append(dict(row, candidate_id=candidate))
        return rows

    preview = _structure(law("G-1", given_is_an_expander=False) + law("G-2", given_is_an_expander=True))
    assert preview["verdicts"] == {"finite dimension": 2}, "the chain from empty alone reads both finite"
    assert preview["chains_agreement"] == {"both chains finite": 1, "chains disagree on structure": 1}
    by_law = {row["candidate_id"]: row for row in preview["finite"]}
    assert by_law["G-1"]["given_finite_dimension"] is True
    assert by_law["G-2"]["given_finite_dimension"] is False and "logarithm" in by_law["G-2"]["given_why"]
    assert SR.law_structure(law("G-2", given_is_an_expander=True), chain="given")["chain"] == "given"


def test_the_reading_applies_the_gate_s_log_diameter_flag_and_row_choice():
    from types import SimpleNamespace

    from graph_scale_dynamics.decisions import structure_gate as SG
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.research.record_report import _structure

    hist = {"2": 40, "3": 60}

    def law(candidate, flag):
        rows = []
        for n in (4096, 16384, 65536):
            for seed in (0, 1):
                row = _seed(n, hist, n, 4.0 / n, int(n ** 0.5))
                row["seed"] = seed
                row["metrics"]["log_diameter_flag"] = flag
                rows.append(dict(row, candidate_id=candidate))
        return rows

    clean, raised = law("G-clean", False), law("G-raised", True)
    assert SR.law_structure(clean)["finite_dimension"] is True
    flagged = SR.law_structure(raised)
    assert flagged["finite_dimension"] is None and flagged["code"] == SG.LOG_DIAMETER_RAISED
    assert "log-diameter flag is raised on 2 seed(s) at N=65536" in flagged["why"]
    assert SR.law_structure(raised, chain="given")["finite_dimension"] is True, "the flag is the chain from empty's own"
    for rows, result in ((clean, SG.FINITE), (raised, SG.UNDECIDABLE)):
        rungs = [SimpleNamespace(n=n, structure=s) for n, s in sorted(SG.rung_structure(rows).items())]
        assert SG.read_chains(rungs, SG.thresholds_of(Policy()))["result"] == result
    preview = _structure(clean + raised)
    assert preview["chains_agreement"] == {"both chains finite": 1, "a chain not decidable yet": 1}
    assert preview["verdicts"] == {"finite dimension": 1, "not decidable yet": 1}
    assert SR.law_structure(clean)["rungs"][-1]["seeds"] == 2
