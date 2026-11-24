from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CLAIM_LEDGER_CONTRACT = "gsd-claim-ledger-1"

VERIFIED = "VERIFIED"
REFUTED = "REFUTED"
UNCHECKABLE = "UNCHECKABLE"

LANE_TREE = "tree"

ROOT = Path(__file__).resolve().parents[2]
SURVEY_CONFIG = ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json"
INSTRUMENT_CHECK = ROOT / "graph_scale_dynamics" / "calibration" / "instrument_check.py"


_HANDOFF = "docs/agent/HANDOFF.md, build 496 handover"

@dataclass(frozen=True)
class Claim:
    claim_id: str
    statement: str
    asserted_in: str
    lane: str
    check: Callable


def _finding(verdict: str, expected, measured, reading: str) -> dict:
    return {"verdict": verdict, "expected": expected, "measured": measured, "reading": reading}


def _verdict(holds: bool) -> str:
    return VERIFIED if holds else REFUTED


def _survey() -> dict:
    return json.loads(SURVEY_CONFIG.read_text(encoding="utf-8"))


def _number(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


DS_NOISE_FLOOR_STATED = 0.234


def _check_ds_noise_floor() -> dict:
    from graph_scale_dynamics.research.score_door import table_noise_floors
    floors = table_noise_floors()[0]
    measured = _number((floors or {}).get("d_s"))
    if measured is None:
        return _finding(UNCHECKABLE, DS_NOISE_FLOOR_STATED, floors,
                        "the calibration table loaded but carries no d_s noise floor, so the "
                        f"stated {DS_NOISE_FLOOR_STATED} has nothing in this tree to be compared against.")
    holds = abs(measured - DS_NOISE_FLOOR_STATED) <= 0.0005
    return _finding(_verdict(holds), DS_NOISE_FLOOR_STATED, measured,
                    f"the table in force reads a d_s noise floor of {measured:.6f}, which is "
                    f"{'within' if holds else 'outside'} 0.0005 of the stated {DS_NOISE_FLOOR_STATED}.")


def _check_mean_degree_window() -> dict:
    window = (_survey().get("limits") or {}).get("mean_degree_window") or {}
    low, high = _number(window.get("min")), _number(window.get("max"))
    holds = low == 0.0 and high == 16.0
    return _finding(_verdict(holds), {"min": 0.0, "max": 16.0}, window,
                    f"the campaign template's mean-degree window is {low} to {high}.")


def _check_connectivity_floor() -> dict:
    survey = _survey()
    limits = _number((survey.get("limits") or {}).get("connectivity_floor"))
    engine = _number(((survey.get("engine") or {}).get("policy") or {}).get("connectivity_floor"))
    measured = {"limits.connectivity_floor": limits, "engine.policy.connectivity_floor": engine}
    holds = limits == 0.5 and engine == 0.5
    agree = "and they agree" if limits == engine else "and they disagree with each other"
    return _finding(_verdict(holds), 0.5, measured,
                    f"the template states the connectivity floor twice, as {limits} and {engine}, {agree}.")


def _check_deep_lane_widths() -> dict:
    rows = ((_survey().get("engine") or {}).get("policy") or {}).get("deep_lane_widths") or []
    widths = {int(row[0]): int(row[1]) for row in rows if len(row) >= 2}
    expected = {1048576: 4}
    holds = widths == expected
    return _finding(_verdict(holds), expected, widths,
                    f"the deep lane is {widths.get(1048576)} wide at N=1,048,576, the ladder's top.")


def _check_audit_fraction() -> dict:
    measured = _number(((_survey().get("engine") or {}).get("policy") or {}).get("audit_fraction"))
    holds = measured == 0.1
    share = f"{measured:.0%}" if measured is not None else "no"
    return _finding(_verdict(holds), 0.1, measured,
                    f"the engine policy audits a {share} sample.")


def _check_chains_split_z() -> dict:
    measured = _number((_survey().get("policy") or {}).get("equilibration_split_z"))
    holds = measured is not None and measured <= 3.0
    return _finding(_verdict(holds), 3.0, measured,
                    f"a rung is certified between its chains at a split z of {measured}.")


def _check_stationarity_drift_bound() -> dict:
    measured = _number((_survey().get("policy") or {}).get("stationarity_drift_max"))
    holds = measured == 3.0
    return _finding(_verdict(holds), 3.0, measured,
                    f"the stationarity drift bound in force is {measured} of a chain's own errors.")


def _check_depth_is_bought_on_ds_alone() -> dict:
    from graph_scale_dynamics.decisions.engine import SETTLING_RULES
    measured = sorted(SETTLING_RULES)
    holds = SETTLING_RULES == frozenset({"d_s_settled"})
    tail = "nothing else settles a law" if holds else "so something other than d_s settles a law too"
    return _finding(_verdict(holds), ["d_s_settled"], measured,
                    f"the decision engine settles a law on {measured}; {tail}. Other rules buy rungs too.")


def _check_aicc_threshold() -> dict:
    from graph_scale_dynamics.measurements.estimators import DIFFUSIVE_WINDOW_MIN_DELTA_AICC
    measured = _number(DIFFUSIVE_WINDOW_MIN_DELTA_AICC)
    holds = measured == 2.0
    return _finding(_verdict(holds), 2.0, measured,
                    f"a d_s reading is withheld unless the power law beats spectral-gap decay "
                    f"by more than {measured} AICc.")


def _check_analysis_contract() -> dict:
    import inspect

    from graph_scale_dynamics.measurements import estimators
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    holds = "diffusive_window_evidence(" in inspect.getsource(estimators._fit_the_latest_stretch)
    return _finding(_verdict(holds), "carried", "carried" if holds else "gone",
                    f"the AICc null is part of the one analysis the tree measures with, {ANALYSIS_VERSION}.")


def _check_degree_anchor_identity() -> dict:
    from graph_scale_dynamics.research.hamiltonian_preflight import effective_basis
    spec = {"terms": [{"op": "degree_anchor", "params": {"k": 3}, "coeff": {"c0": 1.0, "scale": "one"}}],
            "dynamics": {"beta": 1.0}}
    basis = effective_basis(spec)
    measured = {str(term.get("op")): _number(term.get("coefficient")) for term in basis}
    expected = {"degree_square_sum": 1.0, "edge_count": -12.0}
    holds = measured == expected
    return _finding(_verdict(holds), expected, measured,
                    f"a degree_anchor at k=3 reduces to {measured}, so it adds no basis direction "
                    f"that degree_square_sum and edge_count do not already span.")


def _check_degree_square_sum_exists() -> dict:
    from graph_scale_dynamics.dsl.dsl import OPERATORS
    present = "degree_square_sum" in OPERATORS
    return _finding(_verdict(present), "degree_square_sum in OPERATORS",
                    {"present": present, "operator_count": len(OPERATORS)},
                    f"the DSL ships {len(OPERATORS)} terms and degree_square_sum is "
                    f"{'among' if present else 'not among'} them.")


def _check_calibration_table_gates_a_release() -> dict:
    flat = " ".join(INSTRUMENT_CHECK.read_text(encoding="utf-8").split())
    found = re.search(r"[^.]*gates a release[^.]*\.", flat)
    if found is None:
        return _finding(VERIFIED, "no release gate in calibration/instrument_check.py", None,
                        "nothing in the instrument check claims a release gate, so the calibration "
                        "table gates nothing.")
    sentence = found.group(0).strip()
    return _finding(REFUTED, "no release gate in calibration/instrument_check.py", sentence,
                    f"the instrument check states it: \"{sentence}\" The table gates a release on "
                    f"d_s, so the claim that it gates nothing is false.")


def _check_term_subset_is_expressible() -> dict:
    from graph_scale_dynamics.scheduling.term_selection import preflight
    survey = _survey()
    grid = (survey.get("search_policy") or {}).get("grid")
    out = preflight(["degree_square_sum", "edge_count"], grid, survey.get("complexity_budget"))
    status = str(out.get("status"))
    sample = out.get("sample") or {}
    measured = {"status": status, "problems": out.get("problems"),
                "laws_drawn": sample.get("laws_drawn"), "distinct_physical": sample.get("distinct_physical")}
    holds = status == "PASS"
    return _finding(_verdict(holds), "PASS", measured,
                    f"a two-term selection against the shipped grid is {status}, drawing "
                    f"{sample.get('laws_drawn')} laws of which {sample.get('distinct_physical')} are "
                    f"distinct physics.")


def _check_build_number_and_consolidation() -> dict:
    build = int((ROOT / "BUILD_NUMBER").read_text(encoding="utf-8").strip())
    heading = (ROOT / "docs" / "agent" / "NEXT_BUILD.md").read_text(encoding="utf-8").splitlines()[0]
    named = re.search(r"#\s*The next build is\s+(\d+)\s*$", heading)
    text = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    cadence = re.search(r"^Consolidation builds:\s*(\S.*?)\s*$", text, re.M)
    planned = re.search(r"^Next consolidation", text, re.M)
    next_build = int(named.group(1)) if named else None
    expected = {"next_build": "BUILD_NUMBER + 1",
                "consolidation": "when one is needed, on no schedule (2026-11-24), no line planning the next"}
    measured = {"BUILD_NUMBER": build, "next_build": next_build,
                "consolidation": cadence.group(1) if cadence else None, "a next one planned": bool(planned)}
    if next_build is None or cadence is None:
        return _finding(UNCHECKABLE, expected, measured,
                        "docs/agent/NEXT_BUILD.md or docs/ROADMAP.md no longer carries the line this "
                        "claim is read from, so the next build and the consolidation cadence cannot be read.")
    holds = next_build in (build + 1, build + 2) and not planned
    return _finding(_verdict(holds), expected, measured,
                    f"the tree is build {build}, names {next_build} as the next build, and the roadmap says a "
                    f"consolidation comes {cadence.group(1)}" + (", yet still plans the next one." if planned else "."))


def tree_claims() -> list[Claim]:
    return [
        Claim("ds_noise_floor", f"the d_s calibration noise floor is {DS_NOISE_FLOOR_STATED}",
              "docs/HISTORY.md, build 529; " + _HANDOFF, LANE_TREE, _check_ds_noise_floor),
        Claim("mean_degree_window", "the campaign's mean-degree window is 0 to 16",
              _HANDOFF, LANE_TREE, _check_mean_degree_window),
        Claim("connectivity_floor", "the connectivity floor is 0.5",
              _HANDOFF, LANE_TREE, _check_connectivity_floor),
        Claim("deep_lane_widths", "the lane is 4 wide at N=1,048,576, the ladder's top",
              _HANDOFF, LANE_TREE, _check_deep_lane_widths),
        Claim("audit_fraction", "the engine audits a 10% sample",
              _HANDOFF, LANE_TREE, _check_audit_fraction),
        Claim("chains_split_z", "a rung is certified between its chains at z at most 3",
              _HANDOFF, LANE_TREE, _check_chains_split_z),
        Claim("stationarity_drift_bound", "the stationarity drift bound is 3 of a chain's own errors",
              _HANDOFF, LANE_TREE, _check_stationarity_drift_bound),
        Claim("depth_is_bought_on_ds_alone",
              "of the rules that settle a law, d_s alone does; mean-degree settling decides nothing",
              "build 481's call, carried in calibration/instrument_check.py", LANE_TREE,
              _check_depth_is_bought_on_ds_alone),
        Claim("aicc_threshold",
              "a d_s reading is withheld unless the power law beats spectral-gap decay by more than 2 AICc",
              "docs/HISTORY.md, build 490", LANE_TREE, _check_aicc_threshold),
        Claim("analysis_contract", "the AICc null arrived in analysis-3.0.0",
              _HANDOFF, LANE_TREE, _check_analysis_contract),
        Claim("degree_anchor_identity",
              "degree_anchor is exactly degree_square_sum minus 4k*edge_count plus a constant, "
              "so cutting it loses no expressible physics",
              _HANDOFF, LANE_TREE, _check_degree_anchor_identity),
        Claim("degree_square_sum_exists", "degree_square_sum is a DSL term available to a campaign today",
              _HANDOFF, LANE_TREE, _check_degree_square_sum_exists),
        Claim("calibration_table_gates_a_release", "the calibration table gates nothing",
              _HANDOFF, LANE_TREE, _check_calibration_table_gates_a_release),
        Claim("term_subset_is_expressible", "a campaign can be run on a subset of the thirteen terms",
              _HANDOFF, LANE_TREE, _check_term_subset_is_expressible),
        Claim("build_number_and_consolidation",
              "the file naming the next build is current and the roadmap says how a consolidation comes, planning none",
              "docs/agent/NEXT_BUILD.md; docs/ROADMAP.md", LANE_TREE,
              _check_build_number_and_consolidation),
    ]


def _record(claim: Claim, args: tuple) -> dict:
    row = {"claim_id": claim.claim_id, "statement": claim.statement,
           "asserted_in": claim.asserted_in, "lane": claim.lane}
    try:
        found = claim.check(*args) or {}
    except Exception as error:
        return row | {"verdict": UNCHECKABLE, "expected": None, "measured": None,
                      "reading": f"the check could not run: {type(error).__name__}: {error}"}
    verdict = str(found.get("verdict") or UNCHECKABLE)
    return row | {"verdict": verdict, "expected": found.get("expected"),
                  "measured": found.get("measured"),
                  "reading": str(found.get("reading") or "the check returned no reading.")}


def _evaluate(claims: list[Claim], lane: str, args: tuple) -> dict:
    records = [_record(claim, args) for claim in claims]
    counts = {verdict: sum(1 for row in records if row["verdict"] == verdict)
              for verdict in (VERIFIED, REFUTED, UNCHECKABLE)}
    summary = (f"{len(records)} {lane} claims: {counts[VERIFIED]} verified, {counts[REFUTED]} refuted, "
               f"{counts[UNCHECKABLE]} not checkable here.")
    readings = [summary] + [f"{row['claim_id']}: {row['verdict']} -- {row['reading']}" for row in records]
    return {"contract": CLAIM_LEDGER_CONTRACT, "lane": lane, "claims": records,
            "counts": counts, "readings": readings}


def evaluate_tree() -> dict:
    return _evaluate(tree_claims(), LANE_TREE, ())
