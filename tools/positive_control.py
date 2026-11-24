#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import law_rows as L  # noqa: E402
from graph_scale_dynamics.domain import chain_list as CL  # noqa: E402
from graph_scale_dynamics.research.control_verdict import (  # noqa: E402
    CAMPAIGN_OF, FINITE, control_laws, judge, STEM)

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "positive_control_criterion.json"
CRITERION_2 = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json"
GROWTH_CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_3.json"
ONLY_IN_A_GROWTH_STUDY = frozenset({"gsd-controls-criterion-3"})


def _as_folder(path: Path) -> Path:
    path = Path(path)
    if path.is_dir():
        return path
    from read_bundle import scratch_dir

    from graph_scale_dynamics.research.bundle_layout import extract
    return extract(path, scratch_dir("gsd-control-check-"))


def load_criterion(path: Path = CRITERION) -> dict:
    from graph_scale_dynamics.resources import committed
    return committed.read(path)


def _parts(path: Path, criterion: dict) -> list[Path]:
    study = next(iter(sorted(Path(path).rglob("study.json"))), None)
    name = CAMPAIGN_OF.get(criterion.get("contract")) or criterion.get("campaign")
    if study is not None and name:
        listed = json.loads(study.read_text(encoding="utf-8")).get("campaigns") or []
        return [study.parent / str(c["bundle"]) for c in listed if c.get("name") == name and c.get("bundle")]
    return [Path(path)]


def chains_from_bundle(path: Path, criterion: dict | None = None) -> dict:
    found = {}
    for part in (_parts(Path(path), criterion) if criterion is not None else [Path(path)]):
        for body in L.bodies(part):
            section = (body.get("the_record") or {}).get("structure_by_the_committed_rule") or {}
            for row in section.get("chains_by_law") or []:
                found[str(row["candidate_id"])] = row
    return found


def probes_from_bundle(path: Path, criterion: dict, chain: str = "given") -> dict:
    found = {}
    for part in _parts(Path(path), criterion):
        for body in L.bodies(part):
            section = (body.get("the_record") or {}).get("structure_by_the_committed_rule") or {}
            found.update(section.get(f"{STEM[chain]}_probes_by_law") or {})
    return found


def render(result: dict) -> str:
    lines = [f"positive control ({result['criterion']}, committed {result['committed_utc']}): {result['overall'].upper()}"]
    for row in result["laws"]:
        detail = (f"from empty {row.get('empty')}"
                  + (f" (d_s from its gap {row['from_empty_implied_d_s']:.2f})" if row.get("from_empty_implied_d_s") else "")
                  + f", given {row.get('given')}"
                  + (f" (d_s from its gap {row['given_implied_d_s']:.2f})" if row.get("given_implied_d_s") else ""))
        lines.append(f"  {row['label']} {row['role']:8s} {row['verdict']:17s} {row['what']}")
        lines.append(f"      {detail if 'empty' in row else ''}{'; ' if 'empty' in row else ''}{row['why']}")
        for chain in ("empty", "given"):
            if row.get(f"{STEM[chain]}_probes"):
                lines.append(f"      {chain} probes (top two rungs read): " + "; ".join(
                    f"{probe} " + (", ".join(f"{v} at {n:,}" for n, v in pairs) or "not read")
                    for probe, pairs in row[f"{STEM[chain]}_probes"].items()))
    return "\n".join(lines)


def cmd_laws(args) -> int:
    criterion = load_criterion()
    laws = [{"candidate_id": law["candidate_id"], "settled": False, "label": f"{law['label']}: {law['what']}",
             "spec": law["spec"]} for law in control_laws(criterion)]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"contract": "gsd-benchmark-laws-1", "source": "538 positive control",
                               "criterion": criterion["contract"], "laws": laws}, indent=2))
    print(f"{len(laws)} positive-control laws -> {out}")
    return 0


def _laws_in(part: Path) -> set[str]:
    return {law for body in L.bodies(part) for law in L.latest(body)}


def _for_a_lone_part(bundle: Path, criteria: list[dict]) -> list[dict]:
    held = _laws_in(bundle)
    fitting = [c for c in criteria if {law["candidate_id"] for law in control_laws(c)} <= held]
    most = max((len(c["laws"]) for c in fitting), default=0)
    return [c for c in fitting if len(c["laws"]) == most] or criteria[:1]


def judged_in_this_study(bundle: Path, criteria: list[dict]) -> list[dict]:
    from graph_scale_dynamics.operations.study_design import design_for
    from graph_scale_dynamics.research.control_verdict import for_campaign, judged_by
    study = next(iter(sorted(Path(bundle).rglob("study.json"))), None)
    if study is None:
        return criteria
    try:
        design = design_for(ROOT, str(json.loads(study.read_text(encoding="utf-8")).get("study_id") or ""))
    except ValueError:
        design = None
    judging = judged_by(design)
    if judging is None:
        return criteria
    out = []
    for criterion in criteria:
        part = for_campaign(judging, CAMPAIGN_OF.get(criterion.get("contract")) or "")
        out.append(part if part is not None else criterion)
    return out


def parts_of(criterion: dict) -> list[dict]:
    from graph_scale_dynamics.research.control_verdict import for_campaign
    if "campaigns" not in criterion:
        return [criterion]
    return [for_campaign(criterion, name) for name in criterion["campaigns"]]


def cmd_check(args) -> int:
    criteria = (parts_of(load_criterion(Path(args.criterion))) if args.criterion else
                [load_criterion(path) for path in (CRITERION_2, GROWTH_CRITERION)
                 if path.is_file()])
    bundle = _as_folder(Path(args.bundle))
    if not args.criterion and next(iter(bundle.rglob("study.json")), None) is None:
        criteria = _for_a_lone_part(bundle, criteria)
    if not args.criterion:
        criteria = judged_in_this_study(bundle, criteria)
    outcomes = []
    for criterion in criteria:
        if (next(iter(bundle.rglob("study.json")), None) is not None and not _parts(bundle, criterion)):
            print(f"{criterion['contract']}: no campaign "
                  f"{CAMPAIGN_OF.get(criterion['contract']) or criterion.get('campaign')} in this bundle")
            if criterion["contract"] not in ONLY_IN_A_GROWTH_STUDY:
                outcomes.append("missing")
            continue
        result = judge(criterion, chains_from_bundle(bundle, criterion), probes_from_bundle(bundle, criterion),
                       probes_from_bundle(bundle, criterion, chain="empty"))
        outcomes.append(result["overall"])
        print(json.dumps(result, indent=2) if args.json else render(result))
    return 0 if outcomes and all(o == "pass" for o in outcomes) else 1


def sandbox_rows(law: dict, spec_of_campaign: dict, sizes, seeds, simulate) -> list[dict]:
    from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope, run_one_shot
    from graph_scale_dynamics.scheduling.job_creation import initial_sweeps_multiplier, one_shot_policy
    rows = []
    for n in sizes:
        policy = one_shot_policy(spec_of_campaign, int(n), law["candidate_id"])
        for seed in range(seeds):
            envelope = run_one_shot(law["spec"], int(n), seed, one_shot=policy,
                                    initial_multiplier=initial_sweeps_multiplier(spec_of_campaign, int(n)),
                                    simulate=simulate)
            metrics, _ = analyze_one_shot_envelope(envelope, seed=seed)
            rows.append({"candidate_id": law["candidate_id"], "n": int(n), "seed": seed, "metrics": metrics,
                         "given_start": CL.record(envelope, CL.GIVEN).get("init")})
    return rows


def cmd_sandbox(args) -> int:
    from graph_scale_dynamics.research.structure_reading import law_structure
    from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
    sys.path.insert(0, str(ROOT / "tools"))
    from benchmark_campaign import DEFAULT_SPEC, control_spec
    if args.criterion:
        from graph_scale_dynamics.operations import standing_controls
        criterion = load_criterion(Path(args.criterion))
        campaign = standing_controls.campaign_spec(criterion)
    else:
        criterion = load_criterion()
        campaign = control_spec(json.loads(DEFAULT_SPEC.read_text()))
    engine, simulate, _ = resolve_engine({})
    words = {True: FINITE, False: "no finite dimension", None: "not decidable yet"}
    from graph_scale_dynamics.research.record_report import _from_empty_probes_by_law, _given_probes_by_law
    chains, starts, probes, from_empty_probes = {}, {}, {}, {}
    for law in control_laws(criterion):
        started = time.time()
        rows = sandbox_rows(law, campaign, args.sizes, args.seeds, simulate)
        probes.update(_given_probes_by_law({law["candidate_id"]: rows}))
        from_empty_probes.update(_from_empty_probes_by_law({law["candidate_id"]: rows}))
        from_empty, given = law_structure(rows), law_structure(rows, chain="given")
        chains[law["candidate_id"]] = {"empty": words[from_empty["finite_dimension"]],
                                       "given": words[given["finite_dimension"]],
                                       "from_empty_implied_d_s": from_empty.get("implied_spectral_dimension"),
                                       "given_implied_d_s": given.get("implied_spectral_dimension")}
        starts[law["label"]] = sorted({r["given_start"] for r in rows})
        print(f"{law['label']}: {time.time() - started:.0f} s on the {engine} engine; the given chain started from "
              f"{', '.join(starts[law['label']])}", file=sys.stderr)
    result = judge(criterion, chains, probes, from_empty_probes)
    result.update(sandbox={"sizes": list(args.sizes), "seeds": args.seeds, "engine": engine, "given_start": starts,
                           "note": "the sandbox's sizes, not the campaign's; the criterion is judged on the campaign"})
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0 if result["overall"] == "pass" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/positive_control.py: see docs/TOOLS.md")
    sub = parser.add_subparsers(dest="cmd", required=True)
    laws = sub.add_parser("laws", help="write the control's law set for `benchmark_campaign.py start --kind control`")
    laws.add_argument("--output", default="var/specs/positive_control_laws.json")
    laws.set_defaults(func=cmd_laws)
    check = sub.add_parser("check", help="judge the criterion on a bundle")
    check.add_argument("bundle")
    check.add_argument("--criterion", help="one criterion file; by default every committed one, each on its campaign")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)
    sandbox = sub.add_parser("sandbox", help="run the laws through the pipeline's own path here, no fleet")
    sandbox.add_argument("--sizes", type=int, nargs="+", default=[1024, 4096, 16384])
    sandbox.add_argument("--seeds", type=int, default=2)
    sandbox.add_argument("--criterion", help="a criterion file (542's standing controls); 538's by default")
    sandbox.add_argument("--json", action="store_true")
    sandbox.set_defaults(func=cmd_sandbox)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
