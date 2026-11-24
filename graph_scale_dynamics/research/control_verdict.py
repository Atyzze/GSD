from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics import PROJECT_ROOT

READINGS = Path(PROJECT_ROOT) / "graph_scale_dynamics" / "resources" / "readings"
CRITERIA = {"campaign-positive-control": READINGS / "positive_control_criterion.json",
            "campaign-standing-controls": READINGS / "controls_criterion_2.json",
            "campaign-growth-controls": READINGS / "controls_criterion_3.json"}
CAMPAIGN_OF = {"gsd-positive-control-criterion-1": "campaign-positive-control",
               "gsd-controls-criterion-2": "campaign-standing-controls",
               "gsd-controls-criterion-3": "campaign-growth-controls"}
FINITE, NOT_FINITE = "finite dimension", "not finite"
PROBES = ("d_s", "d_V", "d_B", "d_w")
STEM = {"empty": "from_empty", "given": "given"}
WORDS = {True: FINITE, False: "no finite dimension", None: "not decidable yet"}
READ_FROM_N = 16384
def judged_from_n() -> int:
    from graph_scale_dynamics.research.structure_reading import committed_thresholds
    window = (committed_thresholds() or {}).get("gap_window") or (4096, 65536)
    return int(window[1])


def load_criterion(path: Path) -> dict:
    from graph_scale_dynamics.resources import committed
    return committed.read(path)


def for_campaign(criterion: dict, name: str) -> dict | None:
    if "campaigns" not in criterion:
        return criterion if CAMPAIGN_OF.get(criterion.get("contract")) == name else None
    part = (criterion.get("campaigns") or {}).get(name)
    if part is None:
        return None
    return dict({k: v for k, v in criterion.items() if k != "campaigns"}, campaign=name, **part)


def judged_by(design: dict | None) -> dict | None:
    name = (design or {}).get("controls_criterion")
    return load_criterion(READINGS / str(name)) if name and (READINGS / str(name)).is_file() else None


def control_laws(criterion: dict) -> list[dict]:
    from graph_scale_dynamics.dsl.dsl import fingerprint
    return [dict(law, candidate_id=fingerprint(law["spec"])) for law in criterion["laws"]]


def _meets(expected: str | None, got: str | None) -> bool:
    if expected is None:
        return True
    if expected == FINITE:
        return got == FINITE
    return got is not None and got != FINITE


def judge_probes(expect: dict, readings: dict | None, chain: str = "given") -> tuple[str, list[str], dict]:
    from graph_scale_dynamics.measurements.calibration import ladder_tolerance
    theory, family, from_n = expect["theory"], expect["bands"], int(expect.get("from_n", 4096))
    to_n = int(expect["to_n"]) if expect.get("to_n") else None
    problems, shown, undecided = [], {}, False
    for probe in PROBES:
        read = sorted((int(n), row[probe]["mean"]) for n, row in (readings or {}).items()
                      if int(n) >= from_n and (to_n is None or int(n) <= to_n)
                      and (row.get(probe) or {}).get("mean") is not None
                      and ladder_tolerance(family, probe, int(n)) is not None)
        top = read[-2:]
        shown[probe] = [(n, round(v, 3)) for n, v in top]
        if len(top) < 2:
            undecided = True
            continue
        for n, value in top:
            band = ladder_tolerance(family, probe, n)
            if abs(value - float(theory[probe])) > band:
                problems.append(f"{chain} {probe} {value:.2f} at N={n:,}, the answer {theory[probe]} +/- {band}")
    return ("fail" if problems else "not decidable yet" if undecided else "pass"), problems, shown


def judge(criterion: dict, chains: dict, probes: dict | None = None, from_empty_probes: dict | None = None) -> dict:
    rows, verdicts = [], []
    for law in control_laws(criterion):
        seen = chains.get(law["candidate_id"])
        expect = law["expect"]
        if seen is None:
            rows.append({"label": law["label"], "role": law["role"], "what": law["what"], "verdict": "not read yet",
                         "why": "no reading of this law at 16,384 or above"})
            verdicts.append("not read yet")
            continue
        problems, undecided = [], False
        top = _top_n(seen, (probes or {}).get(law["candidate_id"]))
        for chain in ("empty", "given"):
            if expect.get(chain) == FINITE and seen.get(chain) == "not decidable yet":
                undecided = True
            elif not _meets(expect.get(chain), seen.get(chain)):
                problems.append(f"{chain} expected {expect.get(chain)}, read {seen.get(chain)}")
        for chain in ("empty", "given"):
            low_high = expect.get(f"{STEM[chain]}_implied_d_s")
            implied = seen.get(f"{STEM[chain]}_implied_d_s")
            if low_high and seen.get(chain) == FINITE and not (implied is not None
                                                                and low_high[0] <= implied <= low_high[1]):
                problems.append(f"{chain} d_s from its gap {implied}, expected {low_high[0]} to {low_high[1]}")
        implied = seen.get("given_implied_d_s")
        probe_rows, from_empty_rows = None, None
        if expect.get("given_probes"):
            probe_verdict, probe_problems, probe_rows = judge_probes(expect["given_probes"],
                                                                     (probes or {}).get(law["candidate_id"]))
            problems.extend(probe_problems)
            undecided = undecided or probe_verdict == "not decidable yet"
        if expect.get("from_empty_probes"):
            probe_verdict, probe_problems, from_empty_rows = judge_probes(
                expect["from_empty_probes"], (from_empty_probes or {}).get(law["candidate_id"]), chain="empty")
            problems.extend(probe_problems)
            undecided = undecided or probe_verdict == "not decidable yet"
        verdict = "fail" if problems else ("not decidable yet" if undecided else "pass")
        early = top is not None and top < judged_from_n()
        if early:
            verdict = "running"
        verdicts.append(verdict)
        rows.append({"label": law["label"], "role": law["role"], "what": law["what"], "verdict": verdict,
                     "empty": seen.get("empty"), "given": seen.get("given"), "given_implied_d_s": implied,
                     **({"from_empty_implied_d_s": seen.get("from_empty_implied_d_s")}
                        if seen.get("from_empty_implied_d_s") is not None else {}),
                     **({"given_probes": probe_rows} if probe_rows is not None else {}),
                     **({"from_empty_probes": from_empty_rows} if from_empty_rows is not None else {}),
                     "top_n": top,
                     "why": ((f"measured to N={top:,}; judged from N={judged_from_n():,}, where the rule's gap window "
                              f"ends. So far: " if early else "") + ("; ".join(problems) or "as expected"))})
    overall = ("fail" if "fail" in verdicts else "running" if "running" in verdicts
               else "incomplete" if set(verdicts) - {"pass"} else "pass")
    return {"criterion": criterion["contract"], "committed_utc": criterion["committed_utc"], "overall": overall,
            "laws": rows}


def _top_n(seen: dict, probes: dict | None) -> int | None:
    if isinstance(seen.get("top_n"), int):
        return int(seen["top_n"])
    rungs = [int(n) for n in (probes or {})]
    return max(rungs) if rungs else None


def campaign_verdict(repo, campaign: dict) -> dict | None:
    name = str((campaign.get("spec") or {}).get("name") or "")
    path = CRITERIA.get(name)
    stamped = (campaign.get("spec") or {}).get("controls_judged_by")
    if stamped and (READINGS / str(stamped)).is_file():
        path = READINGS / str(stamped)
    if path is None or not path.is_file():
        return None
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.research.record_report import _from_empty_probes_by_law, _given_probes_by_law
    from graph_scale_dynamics.research.structure_reading import law_structure
    criterion = for_campaign(load_criterion(path), name) if stamped else load_criterion(path)
    if criterion is None:
        return None
    campaign_id = str(campaign["campaign_id"])
    version = str((campaign.get("spec") or {}).get("analysis_version") or ANALYSIS_VERSION)
    chains, probes, from_empty_probes = {}, {}, {}
    for law in control_laws(criterion):
        rows = repo.measurements(law["candidate_id"], version, campaign_id)
        if not rows:
            continue
        probes.update(_given_probes_by_law({law["candidate_id"]: rows}))
        from_empty_probes.update(_from_empty_probes_by_law({law["candidate_id"]: rows}))
        if max(int(r["n"]) for r in rows) < READ_FROM_N:
            continue
        from_empty, given = law_structure(rows), law_structure(rows, chain="given")
        chains[law["candidate_id"]] = {"top_n": max(int(r["n"]) for r in rows),
                                       "empty": WORDS[from_empty["finite_dimension"]],
                                       "given": WORDS[given["finite_dimension"]],
                                       "from_empty_implied_d_s": from_empty.get("implied_spectral_dimension"),
                                       "given_implied_d_s": given.get("implied_spectral_dimension")}
    return judge(criterion, chains, probes, from_empty_probes)
