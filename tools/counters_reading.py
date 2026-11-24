#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-counters-reading-1"
SHOWN = 40


def _table(root: Path, name: str):
    with gzip.open(Path(root) / "tables" / name, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _json_of(value):
    if isinstance(value, str) and value[:1] in "{[":
        return json.loads(value)
    return value if isinstance(value, (dict, list)) else {}


def learning_row(row: dict) -> dict:
    facts = _json_of(row.get("facts_json"))
    facts = facts if isinstance(facts, dict) else {}
    signature = facts.get("signature")
    return {"campaign_id": row["campaign_id"], "candidate_id": row["candidate_id"],
            "decision_id": row["decision_id"], "at_n": row["at_n"], "action": row["action"], "rule": row["rule"],
            "salted": facts.get("salted"),
            "signature": signature if signature is None or isinstance(signature, str) else json.dumps(signature)}


def _normal(value):
    return json.loads(json.dumps(value))


def met(policy, n: int) -> dict:
    from graph_scale_dynamics.decisions import gates as G
    return {"shares": {gate: float(policy.live_share(gate, n)) for gate in sorted(G.LET_THROUGH_GATES)},
            "known_results": sorted(str(s) for size, s in policy.known_results if int(size) == int(n))}


def batches_of(root: Path, decisions: list) -> dict:
    study = json.loads((Path(root) / "study.json").read_text(encoding="utf-8"))
    order = {str(c["campaign_id"]): int((c.get("study_design") or {}).get("campaign") or 0)
             for c in study.get("campaigns") or [] if c.get("study_design")}
    rules: dict = defaultdict(set)
    for row in decisions:
        inputs = _json_of(row.get("inputs_json"))
        if isinstance(inputs, dict) and (inputs.get("policy") or {}).get("let_through_rule"):
            rules[str(row["campaign_id"])].add(inputs.get("policy_fingerprint"))
    learning = {c: next(iter(f)) for c, f in rules.items() if len(f) == 1 and c in order}
    common = Counter(learning.values()).most_common(1)
    fingerprint = common[0][0] if common else None
    return {c: order[c] for c, f in learning.items() if f == fingerprint}


def read(root: Path) -> dict:
    from tools.decision_index import DecisionIndex
    with DecisionIndex(root) as index:
        return _read(root, index)


def _read(root: Path, index) -> dict:
    from graph_scale_dynamics.decisions import let_through as LT
    from graph_scale_dynamics.decisions.replay import policy_from_inputs, replay
    from tools.replay_bundle import replay_rows
    replayed = replay_rows(index.every())
    batches = batches_of(root, index.every())
    laws = [{"campaign_id": str(r["campaign_id"]), "candidate_id": str(r["candidate_id"]),
             "number": int(r["candidate_number"]), "campaign_order": batches[str(r["campaign_id"])],
             "ended": True, "verdict_past": None}
            for r in _table(root, "laws.ndjson.gz")
            if str(r["campaign_id"]) in batches and r.get("candidate_number") is not None]
    rows: dict = defaultdict(list)
    learned = []
    for row in index.every():
        rows[(str(row["campaign_id"]), str(row["candidate_id"]))].append(learning_row(row))
        inputs = _json_of(row.get("inputs_json"))
        if str(row["campaign_id"]) in batches and isinstance(inputs, dict) and inputs.get("learned"):
            learned.append(((str(row["campaign_id"]), str(row["decision_id"])), {"learned": inputs["learned"]}))

    def rows_of(keys):
        return [row for key in keys for row in rows.get((str(key[0]), str(key[1])), ())]

    learned.sort(key=lambda pair: (int(pair[1]["learned"]["at_n"]), int(pair[1]["learned"]["batch"])))
    own, study = {}, {}

    def full(key):
        row = index.row(*key)
        return row, _json_of(row.get("inputs_json"))
    if learned:
        first = policy_from_inputs(full(learned[0][0])[1]["policy"])
        for c in batches:
            own[c] = LT.FixedPoints().refresh([law for law in laws if law["campaign_id"] == c], first, own=c)
            study[c] = LT.FixedPoints().refresh(laws, first, own=c)
    per_batch_differ, first_group_differ, changes = [], [], []
    by_gate: dict = defaultdict(Counter)
    decided: dict = defaultdict(Counter)
    learned_from: dict = defaultdict(lambda: defaultdict(set))
    for key, _light in learned:
        row, inputs = full(key)
        c, law = str(row["campaign_id"]), str(row["candidate_id"])
        found = inputs["learned"]
        n, batch = int(found["at_n"]), int(found["batch"])
        policy = policy_from_inputs(inputs["policy"])
        recorded = met(policy, n)
        learned_as = {}
        results = {}
        for way, points in (("batch", own[c]), ("study", study[c])):
            ledger = points.ledger(batch, n, rows_of)
            again = LT.learned_policy(policy, ledger, n) if ledger is not None else None
            learned_as[way] = again
            results[way] = None if again is None else met(again, n)
            learned_from[way][n].add(points.before(batch))
        if results["batch"] != recorded:
            per_batch_differ.append({"campaign_id": c, "candidate_id": law, "at_n": n, "batch": batch,
                                     "recorded": recorded, "read": results["batch"]})
        if batch == 0 and results["study"] != recorded:
            first_group_differ.append({"campaign_id": c, "candidate_id": law, "at_n": n})
        if results["study"] is None or results["study"] == recorded:
            decided[n]["same learning"] += 1
            continue
        for gate in sorted(g for g in recorded["shares"] if recorded["shares"][g] != results["study"]["shares"][g]):
            by_gate[gate][n] += 1
        if recorded["known_results"] != results["study"]["known_results"]:
            by_gate["known results"][n] += 1
        study_policy = learned_as["study"]
        substituted = dict(inputs, policy=dict(inputs["policy"], salt_shares=_normal(list(study_policy.salt_shares)),
                                               known_results=_normal(list(study_policy.known_results))))
        again = replay(substituted)
        moved = (again.action, again.rule) != (row["action"], row["rule"])
        decided[n]["learning changes, decision does not" if not moved else "decision changes"] += 1
        if moved:
            changes.append({"campaign_id": c, "candidate_id": law, "at_n": n, "batch": batch,
                            "recorded": f"{row['action']}:{row['rule']}", "study": f"{again.action}:{again.rule}"})
    return {"contract": CONTRACT, "bundle": Path(root).name, "batches": dict(sorted(batches.items())),
            "replay": {"decisions": replayed["decisions"], "counts": replayed["counts"], "whole": replayed["whole"]},
            "learned_decisions": len(learned),
            "C1_replays": replayed["counts"].get("differs", 0) == 0,
            "C2_per_batch_reproduced": not per_batch_differ, "per_batch_differ": per_batch_differ[:SHOWN],
            "per_batch_differ_count": len(per_batch_differ),
            "C3_first_group_alike": not first_group_differ, "first_group_differ": first_group_differ[:SHOWN],
            "study_wide": {"by_size": {str(n): dict(v) for n, v in sorted(decided.items())},
                           "learning_changed_by_gate": {g: {str(n): k for n, k in sorted(v.items())}
                                                        for g, v in sorted(by_gate.items())},
                           "decisions_that_change": changes, "decisions_that_change_count": len(changes)},
            "laws_learned_from": {way: {str(n): [min(v), max(v)] for n, v in sorted(sizes.items())}
                                  for way, sizes in learned_from.items()}}


def render(found: dict) -> str:
    lines = [f"the gates' counters, each batch's against the study's ({found['contract']}), {found['bundle']}",
             f"batches read together: {', '.join(f'{c} (place {o})' for c, o in found['batches'].items())}",
             f"C1 every decision replays: {found['C1_replays']} ({found['replay']['counts']})",
             f"C2 per batch, the tool's learning gives what was recorded: {found['C2_per_batch_reproduced']} "
             f"({found['per_batch_differ_count']} of {found['learned_decisions']} learned decisions differ)",
             f"C3 the first group is alike either way: {found['C3_first_group_alike']}"]
    for n, counts in found["study_wide"]["by_size"].items():
        lines.append(f"  N={int(n):,}: {counts}")
    for gate, sizes in found["study_wide"]["learning_changed_by_gate"].items():
        lines.append(f"  learning changed, {gate}: {sizes}")
    lines.append(f"decisions that change study-wide: {found['study_wide']['decisions_that_change_count']}")
    for item in found["study_wide"]["decisions_that_change"][:SHOWN]:
        lines.append(f"  {item['campaign_id']} {item['candidate_id'][:12]} N={item['at_n']:,}: "
                     f"{item['recorded']} -> {item['study']}")
    for way, sizes in found["laws_learned_from"].items():
        lines.append(f"laws learned from, {way}: " + ", ".join(f"N={int(n):,} {a} to {b}" for n, (a, b) in sizes.items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/counters_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path, help="a study bundle, unpacked or its .tar.zst")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    from tools.replay_bundle import study_root
    root = args.bundle if args.bundle.is_dir() else study_root(args.bundle)
    found = read(root)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    print(render(found))
    return 0 if found["C1_replays"] and found["C2_per_batch_reproduced"] and found["C3_first_group_alike"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
