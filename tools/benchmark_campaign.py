#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research.bundle_layout import read_report
from graph_scale_dynamics.scheduling.ladder_spec import engine_ladder  # noqa: F401

BANDS = [(0.0, 1.5), (1.5, 4.0), (4.0, 8.0), (8.0, 16.0), (16.0, 1e9)]
DEFAULT_SPEC = ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json"


def _mean_degree(specimen: dict) -> float | None:
    per_n = (specimen.get("phenotype") or {}).get("per_n") or {}
    for n in sorted((int(k) for k in per_n), reverse=True):
        value = (per_n.get(str(n)) or {}).get("mean_degree")
        if value is not None:
            return float(value)
    return None


def cmd_laws(args) -> int:
    from graph_scale_dynamics.db.connection import resolve_target
    from graph_scale_dynamics.db.repo import Repo

    bundle = Path(args.bundle)
    sys.path.insert(0, str(ROOT / "tools"))
    from law_rows import body as report_28
    chains = (report_28(bundle).get("every_chain") or {}).get("laws") or {}
    settled = sorted(cid for cid, chain in chains.items()
                     if float(((chain or {}).get("score") or {}).get("score") or 0) > 0)
    if getattr(args, "ids", None):
        chosen = [line.strip() for line in Path(args.ids).read_text().splitlines() if line.strip()]
        settled = []
    else:
        specimens = read_report(bundle, "05")["body"].get("specimens") or []
        by_band: dict[int, list[str]] = {i: [] for i in range(len(BANDS))}
        for sp in specimens:
            cid = sp.get("candidate_id")
            md = _mean_degree(sp)
            if cid in settled or md is None:
                continue
            for i, (lo, hi) in enumerate(BANDS):
                if lo <= md < hi:
                    by_band[i].append(cid)
                    break
        rng = random.Random(int(args.seed))
        per_band = max(1, int(args.stratified) // len(BANDS))
        chosen = list(settled)
        for i in range(len(BANDS)):
            pool = sorted(by_band[i])
            rng.shuffle(pool)
            chosen.extend(pool[:per_band])
    with Repo(resolve_target("folder")) as repo:
        specs = {c["candidate_id"]: c for c in repo.candidates(str(args.campaign))}
    laws = []
    for cid in chosen:
        row = specs.get(cid)
        if row is None:
            print(f"warning: {cid[:12]} not in campaign {args.campaign}; skipped", file=sys.stderr)
            continue
        laws.append({"candidate_id": cid, "settled": cid in settled,
                     "spec": row["spec"] if isinstance(row["spec"], dict) else json.loads(row["spec"])})
    payload = {"contract": "gsd-benchmark-laws-1", "source_campaign": str(args.campaign),
               "source_bundle": str(bundle), "selection_seed": int(args.seed),
               "bands": BANDS, "laws": laws}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(f"{len(laws)} laws ({sum(1 for l in laws if l['settled'])} settled) -> {out}")
    return 0


def _default_budgets(base: dict):
    from graph_scale_dynamics.decisions.engine import Policy
    policy = Policy.from_spec(base)
    return lambda n: int(policy.work_budget(int(n)))


def _hours(base: dict, hours: float) -> int:
    from graph_scale_dynamics.scheduling.limits import units_for_seconds
    return units_for_seconds(base, hours * 3600.0)


def _hand_fed(spec: dict) -> dict:
    spec["proposer"] = {"pool_min": 1}
    spec["search_policy"] = {"contract": "gsd-hand-1", "kind": "hand"}
    return spec


def benchmark_spec(base: dict) -> dict:
    spec = _hand_fed(json.loads(json.dumps(base)))
    budget = _default_budgets(base)
    sizes = [64, 256, 1024, 4096]
    engine_ladder(spec, base_sizes=sizes, deep_sizes=[], seeds=3, budgets={n: budget(n) for n in sizes})
    policy = spec.get("policy") or {}
    policy["initial_sweeps_multiplier"] = {k: v for k, v in (policy.get("initial_sweeps_multiplier") or {}).items()
                                          if int(k) <= 4096}
    spec["name"] = "engine-reference-benchmark"
    spec["description"] = ("Engine benchmark: a fixed law set submitted by hand, base block 64 to "
                           "4096, the audit sample at 100% so no law is stopped, no deeper rung, no "
                           "proposals. The export of this campaign is the reference bundle every "
                           "engine must reproduce.")
    return spec


LATTICE_BETAS = (5.0, 20.0)


def _law(terms: list[tuple], beta: float, label: str) -> dict:
    spec = {
        "dsl_version": 1,
        "init": "empty",
        "dynamics": {"kind": "equilibrium", "beta": float(beta), "sweeps": 60,
                     "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}},
        "terms": [{"op": op, "params": params, "coeff": {"c0": float(c0), "scale": "one"}}
                  for op, params, c0 in terms],
    }
    return {"label": label, "beta": beta, "spec": spec}


def lattice_laws() -> list[dict]:
    laws: list[dict] = []
    for beta in LATTICE_BETAS:
        laws.append(_law([("degree_anchor", {"k": 4}, 2.0)], beta, "control: anchor d=4 only"))
        laws.append(_law([("degree_anchor", {"k": 6}, 2.0)], beta, "control: anchor d=6 only"))
        laws.append(_law([("degree_anchor", {"k": 3}, 2.0)], beta, "control: anchor d=3 only"))
        laws.append(_law([("degree_anchor", {"k": 4}, 2.0), ("square_count", {}, -1.0)],
                         beta, "square: anchor d=4, squares rewarded, no overlap penalty"))
        for a in (1.0, 2.0):
            for b in (1.0, 2.0):
                for e in (0.5, 1.0):
                    laws.append(_law([("degree_anchor", {"k": 4}, a), ("square_count", {}, -b),
                                      ("square_edge_overlap", {}, e)],
                                     beta, f"square: a={a} b={b} overlap={e}"))
        for e in (0.5, 1.0):
            laws.append(_law([("degree_anchor", {"k": 4}, 2.0), ("square_count", {}, -1.0),
                              ("square_edge_overlap", {}, e), ("triangle_count", {}, 1.0)],
                             beta, f"square: a=2 b=1 overlap={e} triangles penalised"))
        for b in (1.0, 2.0):
            laws.append(_law([("degree_anchor", {"k": 4}, 2.0), ("induced_square_count", {}, -b),
                              ("square_edge_overlap", {}, 1.0)],
                             beta, f"square: induced squares b={b} overlap=1"))
        laws.append(_law([("degree_anchor_abs", {"k": 4}, 2.0), ("square_count", {}, -1.0),
                          ("square_edge_overlap", {}, 1.0)],
                         beta, "square: |d-4| anchor, b=1 overlap=1"))
        for b in (1.0, 2.0):
            for c in (0.5, 1.0):
                laws.append(_law([("degree_anchor", {"k": 6}, 2.0), ("triangle_count", {}, -b),
                                  ("triangle_edge_overlap", {}, c)],
                                 beta, f"triangular: b={b} overlap={c}"))
        laws.append(_law([("degree_anchor", {"k": 4}, 1.0), ("triangle_count", {}, 1.0),
                          ("square_count", {}, -0.5), ("square_edge_overlap", {}, 0.5)],
                         beta, "graphity-like: d=4, triangles penalised, squares rewarded"))
        laws.append(_law([("degree_anchor", {"k": 6}, 1.0), ("triangle_count", {}, -0.5),
                          ("triangle_edge_overlap", {}, 0.5), ("square_count", {}, 0.5)],
                         beta, "graphity-like: d=6, triangles rewarded, squares penalised"))
    return laws


def lattice_spec(base: dict) -> dict:
    spec = _hand_fed(json.loads(json.dumps(base)))
    budget = _default_budgets(base)
    base_sizes, deep_sizes = [64, 256, 1024, 4096], [16384, 65536, 262144]
    budgets = {n: max(budget(n), _hours(base, 4)) for n in base_sizes + deep_sizes}
    engine_ladder(spec, base_sizes=base_sizes, deep_sizes=deep_sizes, seeds=5, budgets=budgets)
    spec["name"] = "campaign-lattice-benchmark"
    spec["complexity_budget"] = 12
    spec["max_active_candidates"] = 48
    spec["description"] = (
        "The lattice benchmark (build 344, an engine campaign since 461): hand-written Hamiltonians "
        "whose ground states are known (square lattice at d=4 with squares rewarded and square "
        "overlap penalised, triangular at d=6, degree-anchor-only controls, graphity-like mixes), "
        "five seeds a rung, the audit sample at 100% so no law is stopped short of its budget, no "
        "proposer, the ladder to 262144 with depth bought when d_s settles. The question is whether "
        "the probes read d=2 with a power-law radius when a plane is the answer, and whether "
        "Metropolis from the empty graph reaches it or glasses first.")
    return spec


CONTROL_CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "positive_control_criterion.json"


def control_spec(base: dict) -> dict:
    from graph_scale_dynamics.resources import committed
    criterion = committed.read(CONTROL_CRITERION)
    spec = _hand_fed(json.loads(json.dumps(base)))
    budget = _default_budgets(base)
    sizes = [int(n) for n in criterion["rungs"]]
    engine_ladder(spec, base_sizes=sizes, deep_sizes=[], seeds=int(criterion["seeds"]),
                  budgets={n: max(budget(n), _hours(base, 4)) for n in sizes})
    policy = spec["policy"]
    policy["initial_sweeps_multiplier"] = {str(n): 4 for n in sizes}
    policy["max_sweeps_multiplier"] = 16
    spec["sampling_contract"] = dict(spec.get("sampling_contract") or {}, max_sweeps_multiplier=16,
                                     given_start=dict(criterion["given_start"]))
    spec["name"] = "campaign-positive-control"
    spec["complexity_budget"] = 12
    spec["max_active_candidates"] = len(criterion["laws"])
    spec["description"] = (
        "The positive control (538): the lattice law at beta 2 and 4, whose torus the empty start cannot reach, "
        "and two negatives (the degree anchor alone, the lattice law at beta 1), each with a given chain started at "
        "the square torus. Rungs 1,024 to 65,536, all in the base block, three seeds, the audit sample at 100% "
        "(a final verdict stops a law only when it holds at two rungs in a row), no proposals. The criterion, "
        "committed before any run: graph_scale_dynamics/resources/readings/positive_control_criterion.json; judge it with "
        "tools/positive_control.py check <bundle>.")
    return spec


def deep_spec(base: dict) -> dict:
    spec = lattice_spec(base)
    spec["name"] = "campaign-deep-relaxation"
    base_sizes, deep_sizes = [64, 256, 1024, 4096, 16384, 65536, 262144], [1048576]
    budgets = {n: _hours(base, 4) for n in base_sizes}
    budgets[1048576] = _hours(base, 24)
    engine_ladder(spec, base_sizes=base_sizes, deep_sizes=deep_sizes, seeds=5, budgets=budgets)
    policy = spec["policy"]
    policy["max_sweeps_multiplier"] = 512
    policy["initial_sweeps_multiplier"] = {"64": 4, "256": 4, "1024": 16, "4096": 16,
                                          "16384": 16, "65536": 16, "262144": 16}
    spec["sampling_contract"]["max_sweeps_multiplier"] = 512
    spec["description"] = (
        "Build 347, an engine campaign since 461: depth for the laws the survey could not equilibrate. "
        "Base block to 262144, five seeds, the sampling certificate bounded by a budget in work of about four "
        "hours a seed rather than the 64x multiplier, 1M above it bought when d_s settles with about 24 hours "
        "of work. Stop rules: mean degree above the window or the seed's budget; the audit sample is "
        "100%, so nothing else stops a law.")
    return spec


def cmd_lattice_laws(args) -> int:
    from graph_scale_dynamics.dsl import dsl
    laws = lattice_laws()
    problems = {law["label"]: dsl.validate(law["spec"], complexity_budget=12)
                for law in laws}
    bad = {k: v for k, v in problems.items() if v}
    if bad:
        for label, why in bad.items():
            print(f"invalid: {label}: {why}", file=sys.stderr)
        return 2
    payload = {"contract": "gsd-benchmark-laws-1", "source": "build 344 lattice benchmark",
               "laws": [{"candidate_id": f"lattice:{i:03d}", "settled": False,
                         "label": law["label"], "beta": law["beta"], "spec": law["spec"]}
                        for i, law in enumerate(laws)]}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(f"{len(laws)} lattice benchmark laws -> {out}")
    return 0


def cmd_start(args) -> int:
    laws = json.loads(Path(args.laws).read_text())["laws"]
    spec_path = Path(args.spec)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    derive = {"lattice": lattice_spec, "deep": deep_spec, "control": control_spec}.get(
        getattr(args, "kind", "engine"), benchmark_spec)
    spec_path.write_text(json.dumps(derive(json.loads(DEFAULT_SPEC.read_text())), indent=2))
    started = subprocess.run([sys.executable, "main.py", "campaign", "start", "--spec", str(spec_path),
                              "--reason", args.reason], cwd=ROOT, capture_output=True, text=True)
    print(started.stdout[-800:])
    if started.returncode != 0:
        print(started.stderr[-800:], file=sys.stderr)
        return started.returncode
    import re
    match = re.search(r"^Campaign (\S+) created", started.stdout, re.MULTILINE)
    if not match:
        print("could not read the campaign id from `campaign start`", file=sys.stderr)
        return 2
    campaign = match.group(1)
    with_tmp = Path(args.spec).parent / "benchmark_law_tmp.json"
    for law in laws:
        with_tmp.write_text(json.dumps(law["spec"]))
        sub = subprocess.run([sys.executable, "main.py", "candidate", "submit", "--campaign", campaign,
                              "--file", str(with_tmp)], cwd=ROOT, capture_output=True, text=True)
        if sub.returncode != 0:
            print(f"submit failed for {law['candidate_id'][:12]}: {sub.stdout[-300:]}{sub.stderr[-300:]}")
            return sub.returncode
    with_tmp.unlink(missing_ok=True)
    print(f"benchmark campaign {campaign}: {len(laws)} laws submitted. A running fleet picks it up on its "
          "next tick (uv run python main.py run starts one), and the next study bundle carries it.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/benchmark_campaign.py: see docs/TOOLS.md")
    sub = parser.add_subparsers(dest="cmd", required=True)
    laws = sub.add_parser("laws")
    laws.add_argument("campaign")
    laws.add_argument("--bundle", required=True)
    laws.add_argument("--output", default="var/specs/benchmark_laws.json")
    laws.add_argument("--ids", help="a file of candidate ids, one per line, instead of the stratified draw")
    laws.add_argument("--stratified", type=int, default=20)
    laws.add_argument("--seed", type=int, default=320)
    laws.set_defaults(func=cmd_laws)
    start = sub.add_parser("start")
    start.add_argument("laws")
    start.add_argument("--spec", default="var/specs/benchmark_campaign.json")
    start.add_argument("--reason", default="engine reference bundle")
    start.add_argument("--kind", choices=("engine", "lattice", "deep", "control"), default="engine",
                       help="engine: base block to 4096, no deeper rung; "
                            "lattice: ladder to 262144, five seeds, depth when d_s settles; "
                            "deep: base block to 262144, certificate bounded by wall time, 1M "
                            "above it; control: the positive control, its given chain at the answer; "
                            "every kind is a decision-engine campaign")
    lattice = sub.add_parser("lattice-laws", help="write the lattice benchmark law set")
    lattice.add_argument("--output", default="var/specs/lattice_laws.json")
    lattice.set_defaults(func=cmd_lattice_laws)
    start.set_defaults(func=cmd_start)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
