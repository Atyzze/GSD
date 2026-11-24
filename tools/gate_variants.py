#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CONTRACT = "gsd-gate-variants-1"
VARIANTS = ("fact_sizes_in_a_row=1", "fact_sizes_in_a_row=4", "one_die=flip")
GOING = ("run_next", "done", "hold")
LISTED = 30


def parsed_variant(text: str) -> tuple[str, str]:
    key, _, value = text.partition("=")
    if not key or not value:
        raise ValueError(f"a variant is key=value, not {text!r}")
    return key.strip(), value.strip()


def _value(raw: str, recorded):
    if raw == "flip":
        return not bool(recorded)
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def changed_inputs(inputs: dict, key: str, raw: str) -> dict:
    policy = dict(inputs["policy"])
    policy[key] = _value(raw, policy.get(key))
    return dict(inputs, policy=policy)


def fate(action: str) -> str:
    return "goes on" if action in GOING else "stops"


def decisions(root: Path, campaigns: set[str] | None):
    with gzip.open(Path(root) / "tables" / "decisions.ndjson.gz", "rt", encoding="utf-8") as rows:
        for line in rows:
            if not line.strip():
                continue
            row = json.loads(line)
            if campaigns is not None and str(row.get("campaign_id")) not in campaigns:
                continue
            inputs = row.get("inputs_json")
            inputs = json.loads(inputs) if isinstance(inputs, str) else inputs
            if not inputs or row.get("at_n") is None:
                continue
            yield row, inputs


def read(root: Path, variants=VARIANTS, campaigns: set[str] | None = None) -> dict:
    from graph_scale_dynamics.decisions.replay import replay
    wanted = [(text, *parsed_variant(text)) for text in variants]
    moved = {text: Counter() for text, *_ in wanted}
    first = {text: {} for text, *_ in wanted}
    read_count, laws, recorded_values = 0, set(), {text: Counter() for text, *_ in wanted}
    for row, inputs in decisions(root, campaigns):
        read_count += 1
        law, n = str(row["candidate_id"]), int(row["at_n"])
        laws.add(law)
        before = f"{row['action']}:{row['rule']}"
        for text, key, raw in wanted:
            recorded_values[text][json.dumps(inputs["policy"].get(key))] += 1
            again = replay(changed_inputs(inputs, key, raw))
            after = f"{again.action}:{again.rule}"
            if after == before:
                continue
            moved[text][(n, before, after)] += 1
            if fate(row["action"]) != fate(again.action):
                earlier = first[text].get(law)
                if earlier is None or n < earlier["n"]:
                    first[text][law] = {"n": n, "recorded": before, "variant": after,
                                        "fate": fate(again.action)}
    out = {"contract": CONTRACT, "bundle": Path(root).name, "decisions": read_count, "laws": len(laws),
           "campaigns": sorted(campaigns) if campaigns else "every campaign", "variants": {}}
    for text, key, raw in wanted:
        by_size: dict = {}
        for law, change in first[text].items():
            entry = by_size.setdefault(change["n"], {"stops": [], "goes on": []})
            entry[change["fate"]].append(law)
        out["variants"][text] = {
            "key": key, "value": raw, "recorded": dict(recorded_values[text]),
            "decisions_moved": sum(moved[text].values()),
            "moved": [{"n": n, "recorded": before, "variant": after, "decisions": count}
                      for (n, before, after), count in sorted(moved[text].items(), key=lambda kv: (kv[0][0], -kv[1]))],
            "laws_whose_fate_changes": len(first[text]),
            "by_size": {str(n): {"stops": len(v["stops"]), "goes on": len(v["goes on"]),
                                 "laws_stopping": sorted(v["stops"])[:LISTED],
                                 "laws_going_on": sorted(v["goes on"])[:LISTED]}
                        for n, v in sorted(by_size.items())}}
    return out


def render(found: dict) -> str:
    lines = [f"the gates under other settings ({found['contract']}), {found['bundle']}: {found['decisions']:,} "
             f"decisions of {found['laws']:,} laws replayed, campaigns {found['campaigns']}; each decision replayed "
             "from its own recorded inputs with one setting changed, the counters as they were (a law the variant "
             "would have stopped earlier has no later decision to read, and one it lets on has none past where it "
             "stopped)"]
    for text, variant in found["variants"].items():
        lines.append(f"{text} (recorded {variant['recorded']}): {variant['decisions_moved']:,} decisions move; "
                     f"{variant['laws_whose_fate_changes']:,} laws change fate, at the first size they would")
        for n, entry in variant["by_size"].items():
            lines.append(f"  N={int(n):,}: {entry['stops']} would stop that went on, {entry['goes on']} would go on "
                         "that stopped")
        for row in variant["moved"][:12]:
            lines.append(f"    N={row['n']:,} {row['recorded']} -> {row['variant']}: {row['decisions']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from disordered_reading import study_campaigns
    from read_bundle import scratch_dir, unpacked
    parser = argparse.ArgumentParser(description="tools/gate_variants.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--variant", action="append", help="key=value of the policy, or key=flip; repeatable")
    parser.add_argument("--every-campaign", action="store_true", help="the controls too")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    root = unpacked(args.bundle, scratch_dir("gsd_variants_"))
    if not (root / "tables" / "decisions.ndjson.gz").is_file():
        print("this bundle carries no decisions table (tables/decisions.ndjson.gz, since 798)", file=sys.stderr)
        return 2
    found = read(root, args.variant or VARIANTS, None if args.every_campaign else study_campaigns(root))
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
