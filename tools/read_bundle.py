#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def unpacked(bundle: Path, scratch: Path) -> Path:
    from graph_scale_dynamics.research.bundle_layout import extract
    root, scratch = Path(bundle), Path(scratch)
    if not root.is_dir():
        extract(root, scratch)
        tops = [p for p in scratch.iterdir() if p.is_dir()]
        root = tops[0] if len(tops) == 1 else scratch
    found = [root] if (root / "study.json").is_file() else sorted(p.parent for p in root.rglob("study.json"))
    return found[0] if found else root


def scratch_dir(prefix: str) -> Path:
    import atexit
    import shutil
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    atexit.register(shutil.rmtree, folder, True)
    return folder


def _unpack(path: Path) -> Path:
    root = unpacked(path, scratch_dir("gsd_bundle_"))
    if (root / "study.json").is_file():
        return root
    found = sorted(p.parent for p in root.rglob("manifest.json"))
    return found[0] if found else root


def _study(root: Path) -> list[Path]:
    study = _load(root, "study.json") or {}
    print(f"study {study.get('study_id')}: build {study.get('build_number')}, built {study.get('built_utc')}; "
          f"{len(study.get('campaigns') or [])} campaign(s), {len(study.get('missing') or [])} missing")
    for c in study.get("campaigns") or []:
        tree = c.get("gate_tree") or {}
        finished = " ".join(f"{int(n):,}:{k}" for n, k in (tree.get("finished_by_rung") or {}).items())
        print(f"  campaign {c.get('campaign_id')} ({(c.get('quadrant') or {}).get('label')}): {c.get('state')}, "
              f"{c.get('laws_drawn', c.get('laws_held'))} laws drawn of budget {c.get('law_budget')}"
              + (f", {c['laws']:,} laws and {c['graphs']:,} simulations" if c.get("graphs") is not None else "")
              + (f" ({c['graphs_finished']:,} graphs)" if c.get("graphs_finished") is not None else "")
              + f"; finished by rung {finished or '-'}")
        withheld, through = tree.get("withheld_by_gate") or {}, tree.get("let_through_by_gate") or {}
        if withheld or through:
            print("    gates: " + ", ".join(f"{g} {withheld.get(g, 0)}/{through.get(g, 0)}"
                                           for g in dict.fromkeys([*withheld, *through]))
                  + "  (withheld/let through)")
    for m in study.get("missing") or []:
        print(f"  campaign {m.get('campaign_id')} missing: {m.get('why')}")
    parts = {p.parent.name: p.parent for p in root.glob("*/manifest.json")}
    order = [c.get("bundle") for c in study.get("campaigns") or [] if c.get("bundle") in parts]
    return [parts[name] for name in order] + [parts[name] for name in sorted(parts) if name not in order]


def _load(root: Path, name: str):
    matches = sorted(root.glob(name))
    if not matches:
        return None
    try:
        data = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("body", data) if isinstance(data, dict) else data


def _gib(value) -> str:
    return f"{(value or 0) / 2**30:.1f} GiB"


def _option(args: list[str], name: str) -> str | None:
    if name not in args:
        return None
    at = args.index(name)
    if at + 1 >= len(args):
        raise SystemExit(f"{name} needs a path")
    value = args[at + 1]
    del args[at:at + 2]
    return value


def _reading_of(path: Path) -> dict:
    from graph_scale_dynamics.reporting import study_reading
    if path.suffix == ".json":
        return study_reading.load_reading(path)
    return study_reading.read_study(_unpack(path))


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    against, out = _option(args, "--against"), _option(args, "--json")
    if not args:
        print("usage: tools/read_bundle.py <bundle> [--against <reading>] [--json <file>]; see docs/TOOLS.md")
        return 2
    root = _unpack(Path(args[0]))
    if (root / "study.json").is_file():
        from graph_scale_dynamics.reporting import study_reading
        reading = study_reading.read_study(root)
        if out:
            Path(out).write_text(json.dumps(reading, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        if against:
            before = _reading_of(Path(against))
            print(study_reading.render_comparison(study_reading.compare(before, reading)))
            return 0
        parts = _study(root)
        print("\n" + study_reading.render(reading))
        for part in parts:
            print("\n" + "=" * 100)
            _campaign(part)
        return 0
    if against or out:
        raise SystemExit("--against and --json read a study bundle; this is one campaign's")
    return _campaign(root)


def _campaign(root: Path) -> int:
    manifest = _load(root, "manifest.json") or {}
    cycle = manifest.get("cycle") or {}
    print(f"bundle {root.name}: build {manifest.get('build_number')}, campaign {manifest.get('campaign_id')}, "
          f"finished {cycle.get('finished_utc')}")
    if cycle.get("snapshot_seconds") is not None:
        peak = cycle.get("snapshot_peak_bytes")
        print(f"report cycle: {cycle.get('total_seconds')} s, snapshot {cycle.get('snapshot_seconds')} s, held "
              f"{_gib(cycle.get('snapshot_resident_bytes'))}, "
              + (f"worker peak {_gib(peak)}" if peak else "worker peak not recorded")
              + f"; {(cycle.get('report_pool') or {}).get('why')}")
        slow = [f"{s['stage']} {s['seconds']:.0f} s" for s in cycle.get("snapshot_stages") or []
                if (s.get("seconds") or 0) >= 3]
        if slow:
            print("  snapshot stages of 3 s or more: " + ", ".join(slow))
        for part in (cycle.get("snapshot_parts") or [])[:8]:
            print(f"  part {part['campaign_id']} {part['part']}: {part['rows']:,} rows, "
                  f"{part['json_bytes'] / 2**20:,.0f} MiB of JSON")

    report = _load(root, "28-*.json") or {}
    record = report.get("the_record") or {}
    if not record:
        print("\nreport 28 has no record section")
    draws = record.get("draw_ledger") or {}
    if draws.get("draws"):
        refused = ", ".join(f"{k} {v['share']:.1%}" for k, v in (draws.get("refused_by_reason") or {}).items())
        print(f"\ndraws: {draws['draws']:,}, admitted {draws.get('admitted_share', 0):.1%}; refused: {refused}")
    audit = record.get("depth_audit") or {}
    if audit:
        print(f"depth audit: {audit.get('audited_decisions')} audited; settled at the withheld rung "
              f"{audit.get('audited_settled_share')} against {audit.get('bought_settled_share')} for bought laws; "
              f"{audit.get('reading') or audit.get('why')}")
    replay = record.get("decision_record") or {}
    if replay:
        print(f"decisions: {replay.get('decisions'):,}; replayed {replay.get('sampled')}, share "
              f"{replay.get('replay_share')}, mismatches {len(replay.get('mismatches') or [])}")
    cost = record.get("cost_per_attempt") or {}
    for contract, part in sorted((cost.get("by_contract") or {"(one contract)": {"by_rung": cost.get("by_rung") or {}}}).items()):
        print(f"cost, {contract}:")
        for n, cols in sorted((part.get("by_rung") or {}).items(), key=lambda kv: int(kv[0])):
            get = lambda k: (cols.get(k) or {}).get("median")  # noqa: E731
            print(f"  n={n:>8}: child {get('child_cpu_seconds')} s, {get('child_write_bytes')} B written; "
                  f"worker {get('bookkeeping_cpu_seconds')} s, {get('bookkeeping_write_bytes')} B")
    structure = record.get("structure_by_the_committed_rule") or {}
    if structure:
        print(f"gate preview: {structure.get('laws_read')} laws read: {structure.get('verdicts')}")
        if structure.get("chains_agreement"):
            print(f"  both chains (526, the rule planned for 528): {structure['chains_agreement']}")
        for law in structure.get("finite") or []:
            given = law.get("given_finite_dimension")
            given_says = "" if "given_finite_dimension" not in law else (
                "; given chain finite too" if given else "; given chain NOT finite" if given is False else "; given chain undecidable")
            print(f"  finite {law['candidate_id'][:10]}: d_s from gap {law.get('implied_spectral_dimension')}; "
                  f"{law['why']}{given_says}")
        for why, count in (structure.get("not_decidable_because") or {}).items():
            print(f"  undecidable x{count}: {why[:150]}")
    meeting = record.get("chains_meeting") or {}
    if meeting.get("rungs"):
        print("\nthe two chains (594): seeds / met or at rest, never / from how many sweeps (quartiles) / share of the run")
        for r in meeting["rungs"]:
            for regime in ("finite", "zero_temperature"):
                part = r.get(regime)
                if not part:
                    continue
                sweeps, share = part.get("sweeps") or {}, part.get("share_of_the_run") or {}
                print(f"  N={r['n']:>9,} {'T>0' if regime == 'finite' else 'T=0'}: {part['seeds']:>6,} / {part['met']:,}, "
                      f"{part['never']:,} / {sweeps.get('q1')}, {sweeps.get('median')}, {sweeps.get('q3')} / "
                      f"{share.get('median')}")

    graphs = (report.get("graphs_by_rung") or {}).get("rungs") or []
    if graphs:
        print("\ngraphs by rung (542): grown / laws / by where their law went / median mean degree / median giant "
              "share / d_s readable / given chain agrees")
        for r in graphs:
            branches = " ".join(f"{k} {v:,}" for k, v in (r.get("by_branch") or {}).items())
            print(f"  N={r['n']:>9,}: {r['graphs']:>7,} / {r['laws']:>6,} / {branches} / "
                  f"{r.get('median_mean_degree')} / {r.get('median_giant_share')} / "
                  f"{r.get('d_s_readable_share')} / {r.get('given_agrees_share')}")

    tree = report.get("gate_tree") or {}
    if tree.get("gates"):
        print("\ngate tree (533): withheld / let through (share) / of those that went on, settled d_s later vs on their own reading")
        for gate in tree["gates"]:
            if gate.get("withheld") or gate.get("let_through"):
                print(f"  {gate['gate']:<20} {gate.get('withheld', 0):>6} / {gate.get('let_through', 0):>5} "
                      f"({gate.get('share_let_through')}) / {gate.get('settled_later_share')} vs "
                      f"{gate.get('unsalted_settled_later_share_at_the_same_rungs')}")

    fleet = _load(root, "25-*.json") or {}
    hours = (fleet.get("fleet_ladder_by_hour") or {}).get("hours") or []
    if hours:
        print("\nfleet ladder by hour, (n: running/queued):")
        for hour in hours[-8:]:
            print(f"  {hour['hour']}: " + "  ".join(f"{r['n']}: {r['running']}/{r['queued']}" for r in hour["rungs"]))
    compute = _load(root, "14-*.json") or {}
    queue = compute.get("analysis_queue_now") or {}
    if queue:
        print(f"analysis queue now: {queue.get('raw_counts')}")

    ledger = _load(root, "evidence/memory_ledger.json") or {}
    if ledger:
        print(f"\nmemory: total {_gib(ledger.get('mem_total_bytes'))}, available {_gib(ledger.get('mem_available_bytes'))}")
        for line in ledger.get("lines") or []:
            if (line.get("bytes") or 0) >= 2**30:
                print(f"  {line['key']:<24} {_gib(line['bytes']):>9}  {line.get('note')}")
        holders = ledger.get("shared_memory_holders") or {}
        for mount in holders.get("tmpfs_mounts") or []:
            if "used_bytes" in mount:
                print(f"  shared: tmpfs {mount['mount']}: {_gib(mount['used_bytes'])}")
        for proc in holders.get("processes") or []:
            if "shmem_bytes" in proc:
                print(f"  shared: {proc['holder']}: {_gib(proc['shmem_bytes'])}")
        if not holders:
            print("  (no record of who holds the shared memory)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
