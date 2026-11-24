#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.services.worker.engine_registry import ENGINES  # noqa: E402

CONTRACT = "gsd-outputs-of-a-law-1"
LAW = "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json"
DESIGN = "tests/fixtures/a_design_of_four_starts.json"
WRITTEN_ON = ("study", "design")
SIZES = {name: (64,) if engine.reference else (64, 256, 1024) for name, engine in ENGINES.items()}
SEEDS = (0, 1)
RECORD_POINTS = 40
MAX_SWEEPS_MULTIPLIER = 2
LONG = 48
LONG_TEXT = 400
TIMED = ("seconds", "wall_", "_wall", "elapsed", "per_second", "started", "finished", "_utc", "duration", "clock")


def _default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (bytes, bytearray)):
        return {"sha256": hashlib.sha256(bytes(value)).hexdigest(), "bytes": len(value)}
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return str(value)


def timed(key) -> bool:
    return isinstance(key, str) and any(word in key for word in TIMED)


def _numbers(value) -> bool:
    if isinstance(value, list):
        return all(_numbers(item) for item in value)
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def plain(document):
    return _short(json.loads(json.dumps(document, default=_default)))


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _short(document):
    if isinstance(document, dict):
        return {key: _short(value) for key, value in document.items() if not timed(key)}
    if isinstance(document, list):
        kept = [_short(value) for value in document]
        if len(kept) <= LONG:
            return kept
        if _numbers(document):
            return {"sha256": _digest(kept), "items": len(kept)}
        return {"sha256": _digest(kept), "items": len(kept), "first": kept[0], "last": kept[-1]}
    if isinstance(document, str) and len(document) > LONG_TEXT and " " not in document:
        return {"sha256": hashlib.sha256(document.encode()).hexdigest(), "characters": len(document)}
    return document


def design() -> dict:
    raw = (ROOT / DESIGN).read_bytes()
    return dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=DESIGN)


def campaign_spec() -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design as SD
    made = design()
    made.pop("starts_reading")
    return SD.campaign_spec(made, control.shipped_spec(), made["campaigns"][0], 0)


def simulate_of(engine: str):
    from graph_scale_dynamics.scaleflow import engine_door
    return engine_door.simulate_of(engine)


def seed_outputs(law: dict, spec: dict, engine: str, n: int, seed: int) -> dict:
    from graph_scale_dynamics.artifact_store.chain_record import build_record
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.observability.chain_mixing import seed_chain_moments
    from graph_scale_dynamics.observability.chains_course import seed_chains_course
    from graph_scale_dynamics.observability.meeting_reading import seed_meeting_reading, seed_more_meeting_readings
    from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope, run_one_shot
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    policy = dict(one_shot_policy(spec, n, fingerprint(law), law), max_sweeps_multiplier=MAX_SWEEPS_MULTIPLIER)
    envelope = run_one_shot(law, n, seed, one_shot=policy, record_points=RECORD_POINTS, simulate=simulate_of(engine))
    metrics, curves = analyze_one_shot_envelope(envelope, seed=seed)
    metrics["chain_mixing"] = seed_chain_moments(envelope)
    metrics["meeting_reading"] = seed_meeting_reading(envelope, metrics.get("census"))
    metrics["more_meeting_readings"] = seed_more_meeting_readings(envelope, metrics.get("census"))
    metrics["chains_course"] = seed_chains_course(envelope)
    return {"envelope": envelope, "metrics": metrics, "curves": curves, "record": build_record(envelope)}


def decision(law: dict, spec: dict, rows: list[dict]) -> dict:
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.decisions.decider import _rungs
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.decisions.every_chain import EMPTY, decide_every_chain
    from graph_scale_dynamics.decisions.evidence import _b143_rung_sampling_state, _rung_cell
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    law_id = fingerprint(law)

    class Repo:
        def measurements(self, _law, _version, _campaign_id):
            return rows

    class Seeds:
        def seed_rows(self, _campaign_id, _law):
            return {}

    store = DecisionStore(Repo(), None, {"campaign_id": "1", "spec": spec})
    sizes = sorted({int(row["n"]) for row in rows})
    summaries = {n: rung_summary([row["metrics"] for row in rows if int(row["n"]) == n]) for n in sizes}
    states = {n: _b143_rung_sampling_state(spec, n, summaries[n], [r["metrics"] for r in rows if int(r["n"]) == n])
              for n in sizes}
    chains = store.law_chains("1", law_id, states, sizes)["chains"]
    entries = {n: _rung_cell(spec, n, summaries[n], states[n]) for n in sizes}
    rungs = {EMPTY: _rungs(Seeds(), "1", law_id, entries)}
    rungs.update({name: _rungs(Seeds(), "1", law_id, cells) for name, cells in chains.items()})
    decided = decide_every_chain(law_id, rungs, Policy.from_spec(spec))
    return {"summaries": summaries, "states": states, "chains": chains, "decision": decided.as_dict()}


def law_outputs(law: dict, spec: dict, rows: list[dict]) -> dict:
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.observability import law_score
    from graph_scale_dynamics.observability.chain_mixing import rung_mixing
    from graph_scale_dynamics.observability.starts_reading import law_reading
    from graph_scale_dynamics.observability.space_score import space_score
    from graph_scale_dynamics.observability.two_chains import stopping_numbers, two_chains
    from graph_scale_dynamics.research.structure_reading import law_structure
    from graph_scale_dynamics.research.what_happened import law_story
    starts = [dict(start) for start in spec["sampling_contract"]["given_starts"]]
    chains = two_chains(rows, given_start="the random start", policy=stopping_numbers(spec), starts=starts)
    five = law_reading(chains, starts)
    first = law_score.given_family(spec, fingerprint(law), law)
    sizes = sorted({int(row["n"]) for row in rows})
    return {"two_chains": chains, "space_score": space_score(chains, law), "starts_reading": five,
            "law_score": law_score.score(chains, five, starts=starts, first_given=first),
            "structure": {chain: law_structure(rows, chain=chain) for chain in ("empty", "given")},
            "what_happened": law_story(rows, None),
            "rung_mixing": {str(n): rung_mixing([r["metrics"] for r in rows if int(r["n"]) == n]) for n in sizes},
            **decision(law, spec, rows)}


def outputs(engines=tuple(ENGINES), sizes: dict | None = None) -> dict:
    law = json.loads((ROOT / LAW).read_text(encoding="utf-8"))
    spec = campaign_spec()
    out = {"contract": CONTRACT, "law": LAW, "design": DESIGN, "seeds": list(SEEDS), "engines": {}}
    for engine in engines:
        seeds, rows = {}, []
        for n in (sizes or SIZES)[engine]:
            for seed in SEEDS:
                made = seed_outputs(law, spec, engine, int(n), int(seed))
                rows.append({"n": int(n), "seed": int(seed), "metrics": json.loads(json.dumps(made["metrics"],
                                                                                              default=_default))})
                seeds[f"{n}/{seed}"] = made
        out["engines"][engine] = {"sizes": [int(n) for n in (sizes or SIZES)[engine]], "seeds": seeds,
                                  "law": law_outputs(law, spec, rows)}
    return plain(out)


def the_outputs(document: dict) -> dict:
    return {key: value for key, value in document.items() if key not in WRITTEN_ON}


def changed(before, after, path: str = "") -> list:
    differences = []

    def walk(x, y, at):
        if isinstance(x, dict) and isinstance(y, dict):
            for name in sorted(set(x) | set(y)):
                if name not in y:
                    differences.append((f"{at}/{name}", "gone"))
                elif name not in x:
                    differences.append((f"{at}/{name}", "new"))
                else:
                    walk(x[name], y[name], f"{at}/{name}")
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                differences.append((at, f"{len(x)} items, now {len(y)}"))
            else:
                for i, (p, q) in enumerate(zip(x, y, strict=True)):
                    walk(p, q, f"{at}[{i}]")
        elif x != y or type(x) is not type(y):
            differences.append((at, x, y))

    walk(before, after, path)
    return differences


def reports(snapshot: dict) -> dict:
    import copy

    from graph_scale_dynamics.research.report_pipeline import BUILDERS
    bodies = {}
    for code in sorted(BUILDERS):
        replication = copy.deepcopy(snapshot)
        first = replication["campaign_snapshots"][0]
        bodies[code] = BUILDERS[code](dict(first, replication_snapshot=replication))
    return json.loads(json.dumps(bodies, sort_keys=True, default=str))


def write(path: Path, document: dict) -> None:
    text = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(gzip.compress(text, compresslevel=9, mtime=0) if path.suffix == ".gz" else text + b"\n")


def read(path: Path) -> dict:
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if Path(path).suffix == ".gz" else raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="what this tree puts out for one law, five chains, both engines")
    parser.add_argument("--write", type=Path, help="where to write the outputs (.json or .json.gz)")
    parser.add_argument("--against", type=Path, help="outputs an earlier tree wrote, to name what changed since")
    args = parser.parse_args(argv)
    if args.write is None and args.against is None:
        parser.error("give --write, --against or both")
    document = outputs()
    if args.write is not None:
        write(args.write, document)
        print(f"{args.write}: {len(document['engines'])} engines, "
              f"{sum(len(e['seeds']) for e in document['engines'].values())} seeds")
    if args.against is None:
        return 0
    earlier = read(args.against)
    on = next((f"{key} {earlier[key]}" for key in WRITTEN_ON if key in earlier), "no design it names")
    print(f"{args.against} was written on {on}; this tree's outputs are on {DESIGN}")
    differences = changed(the_outputs(earlier), the_outputs(document))
    for at, *what in differences:
        print(f"changed {at}: {' -> '.join(json.dumps(w) for w in what)}"[:400])
    print(f"{len(differences)} outputs changed against {args.against}")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
