#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import law_rows as L  # noqa: E402

CONTRACT = "gsd-starts-bundle-1"
LAWS_CONTRACT = "gsd-starts-laws-1"
LATTICES = L.LATTICES
APART_DIMENSIONS = 2


def _latest(parts: list[dict]) -> dict:
    return {law: row for part in parts for law, row in L.latest(part["engine"]).items()}


def _contracts(parts: list[dict]) -> list[str]:
    return sorted({str(((part["every_chain"] or {}).get("starts_reading") or {}).get("contract"))
                   for part in parts if part["drawn"] and (part["every_chain"] or {}).get("starts_reading")})


def _what_the_rule_would_do(label: str, by_n: dict) -> str:
    from graph_scale_dynamics.decisions import starts_rule as FS
    if label in FS.SHAPED:
        return "climbs on a shape"
    if label == "forgets":
        return "parks: every start alike"
    if label == "remembers":
        looks = 0
        for n in sorted((int(k) for k in by_n), reverse=True):
            if n < 4096 or (by_n.get(str(n)) or [None])[0] != "remembers":
                break
            looks += 1
        return "parks: apart twice" if looks >= FS.APART_LOOKS else "one look: apart"
    return "decided as before: no class"


def _report_10(folder: Path) -> list[dict] | None:
    found = sorted(folder.glob("10-*.json"))
    if not found:
        return None
    return list(((json.loads(found[0].read_text(encoding="utf-8")).get("body") or {}).get("decisions")) or [])


def decided_in(root: Path, parts: list[dict]) -> dict:
    from graph_scale_dynamics.reporting import starts_decided as FD
    sections, failed = [], []
    for part in parts:
        if not part["drawn"]:
            continue
        own = (part["every_chain"] or {}).get("starts_decided")
        if isinstance(own, dict) and own.get("contract") == FD.CONTRACT and "error" not in own:
            sections.append(own)
            continue
        if isinstance(own, dict) and own.get("error"):
            failed.append({"campaign": part["campaign_id"], "error": own["error"]})
        rows = _report_10(root / str(part["record"].get("bundle") or ""))
        if rows is None:
            continue
        by_law: dict = defaultdict(list)
        for row in rows:
            by_law[str(row.get("candidate_id"))].append(row)
        sections.append(FD.decided(by_law, from_rules=True))
    return dict(FD.combined(sections), failed_in_report_28=failed)


def _read_sizes(by_n: dict) -> set[int]:
    return {int(n) for n, label in by_n.items() if label and label != "not_read"}


def law_classes(parts: list[dict]) -> dict:
    latest = _latest(parts)
    out = {}
    for part in parts:
        if not part["drawn"]:
            continue
        for law, score in ((part["every_chain"] or {}).get("laws") or {}).items():
            five = (score or {}).get("starts_reading") or {}
            if not five.get("class"):
                continue
            by_n = {str(n): (row or [None])[0] for n, row in (five.get("by_n") or {}).items()}
            read_at = _read_sizes(by_n)
            at_n = five["at_n"] if "at_n" in five else (max(read_at) if five["class"] != "not_read" else None)
            decision = latest.get(str(law)) or {}
            out[str(law)] = {"campaign": part["campaign_id"], "class": five["class"], "at_n": at_n, "by_n": by_n,
                             "fates": {name: (fate or [None])[0] for name, fate in (five.get("fates") or {}).items()},
                             "decision": [decision.get("action"), decision.get("rule"), decision.get("at_n")]}
    return out


def against(first: dict, second: dict) -> dict:
    same, then_now = defaultdict(Counter), defaultdict(Counter)
    both = sorted(set(first) & set(second))
    for law in both:
        one, two = first[law], second[law]
        common = sorted(_read_sizes(one.get("by_n") or {}) & _read_sizes(two.get("by_n") or {}))
        if common:
            size = str(common[-1])
            same[one["by_n"][size]][two["by_n"][size]] += 1
        then_now[one["class"]][two["class"]] += 1
    compared = sum(sum(counts.values()) for counts in same.values())
    return {"laws_in_both": len(both), "only_in_the_first": len(set(first) - set(second)),
            "only_in_the_second": len(set(second) - set(first)), "read_at_a_common_size": compared,
            "same_class_at_the_same_size": sum(counts[label] for label, counts in same.items()),
            "apart_then_alike_now": same["remembers"]["forgets"], "alike_then_apart_now": same["forgets"]["remembers"],
            "at_the_same_size": {label: dict(counts.most_common()) for label, counts in sorted(same.items())},
            "then_and_now": {label: dict(counts.most_common()) for label, counts in sorted(then_now.items())},
            "the_estimate": the_estimate(first, second)}


def the_estimate(first: dict, second: dict) -> dict:
    from graph_scale_dynamics.decisions import starts_rule as FS
    from graph_scale_dynamics.decisions.engine import PARKING_RULES
    out: dict = defaultdict(Counter)
    for law, one in first.items():
        action, rule, at_n = (list(one.get("decision") or []) + [None, None, None])[:3]
        if int(at_n or 0) < 4096 or not (rule in FS.D_S_DEPTH or (rule in PARKING_RULES and rule not in FS.PARKS)):
            continue
        word = _what_the_rule_would_do(one["class"], {n: [label] for n, label in (one.get("by_n") or {}).items()})
        now = ((second.get(law) or {}).get("decision") or [None, "not in the later bundle"])[1]
        out[f"{word} ({'parked' if rule in PARKING_RULES else action})"][str(now)] += 1
    return {key: dict(counts.most_common()) for key, counts in sorted(out.items())}


def read(root: Path, data: dict | None = None) -> dict:
    from graph_scale_dynamics.decisions import starts_rule as FS
    from graph_scale_dynamics.decisions.engine import PARKING_RULES
    data = data or L.study(root)
    parts = data["parts"]
    laws = [law for law in L.drawn_laws(parts) if law["score"]]
    read_laws = [law for law in laws if (law["score"].get("starts_reading") or {}).get("class")]
    latest = _latest(parts)
    classes = Counter(law["score"]["starts_reading"]["class"] for law in read_laws)
    top_alone, none_read = [], []
    fates: dict = defaultdict(Counter)
    no_fate_laws = 0
    no_fate_by_decision = Counter()
    held = []
    named = []
    reaching = []
    against = defaultdict(Counter)
    restart = Counter()
    restart_laws = defaultdict(list)
    for law in read_laws:
        five = law["score"]["starts_reading"]
        by_n = five.get("by_n") or {}
        label = five["class"]
        read_sizes = [int(n) for n, row in by_n.items() if row and row[0] != "not_read"]
        if label == "not_read":
            (top_alone if read_sizes else none_read).append(law["law"])
        decision = latest.get(law["law"]) or {}
        rule = str(decision.get("rule") or law["rule"] or "none")
        lattice_fates = five.get("fates") or {}
        if label != "not_read" and any(fate is None for fate, _kept in lattice_fates.values()):
            no_fate_laws += 1
            no_fate_by_decision[rule] += 1
        for name, (fate, kept) in lattice_fates.items():
            fates[name][fate or "no fate"] += 1
            if fate == "holds":
                held.append({"law": law["law"], "lattice": name, "kept": kept,
                             "zero_temperature": law["zero_temperature"], "terms": law["ops"]})
        if any(fate == "holds" for fate, _kept in lattice_fates.values()):
            named.append(_named(law, label, five))
        if label in ("one_space", "grows", "converts"):
            reaching.append({"law": law["law"][:12], "class": label,
                             "held": {name: kept for name, (fate, kept) in lattice_fates.items() if fate == "holds"}})
        against[label][rule] += 1
        top = int(decision.get("at_n") or law["at_n"] or 0)
        depth = rule in FS.D_S_DEPTH or (rule in PARKING_RULES and rule not in FS.PARKS)
        if top >= 4096 and depth:
            word = _what_the_rule_would_do(label, by_n)
            restart[(word, "parked" if rule in PARKING_RULES else str(decision.get("action") or "?"))] += 1
            restart_laws[word].append(law["law"])
    bands = Counter("0.8 or more" if (h["kept"] or 0) >= 0.8 else "0.5 to 0.8" for h in held)
    whole = [h for h in held if h["kept"] is not None and abs(float(h["kept"]) - 1.0) < 1e-9]
    return {
        "contract": CONTRACT, "bundle": root.name, "reading": _contracts(parts),
        "laws_scored": len(laws), "laws_read": len(read_laws), "classes": dict(classes.most_common()),
        "largest_size_by_the_chain_from_empty_alone": len(top_alone),
        "no_size_read_by_two_chains": len(none_read),
        "fates": {name: dict(counts.most_common()) for name, counts in sorted(fates.items())},
        "laws_with_a_lattice_of_no_fate": no_fate_laws,
        "laws_with_a_lattice_of_no_fate_by_decision": dict(no_fate_by_decision.most_common()),
        "held": {"lattices": len(held), "laws": len({h["law"] for h in held}), "kept": dict(bands),
                 "kept_all_of_it": [{"law": h["law"][:12], "lattice": h["lattice"],
                                     "zero_temperature": h["zero_temperature"], "terms": h["terms"]} for h in whole],
                 "laws_kept_from_0_8": len({h["law"] for h in held if (h["kept"] or 0) >= 0.8}),
                 "laws_named": sorted(named, key=lambda h: (-(h["at_n"] or 0), h["temperature"] == "zero", h["law"])),
                 "at_a_finite_temperature": sum(1 for h in named if h["temperature"] != "zero"),
                 "from_16384": sum(1 for h in named if (h["at_n"] or 0) >= 16384),
                 "holding_another_dimension": sum(1 for h in named if h["holds_another_dimension"])},
        "a_start_reaching_a_shape": reaching,
        "against_the_latest_decision": {label: dict(rules.most_common()) for label, rules in sorted(against.items())},
        "at_a_restart": {f"{word} ({was})": count for (word, was), count in sorted(restart.items())},
        "at_a_restart_laws": {word: sorted(ids)[:20] for word, ids in sorted(restart_laws.items())},
        "decided": decided_in(root, parts),
        "scores": scores_in(laws),
        "reading_note": ("the classes are the bundle's own reading's (`reading`); what the depth rule would make of "
                         "them at a restart counts the laws whose latest decision is one of d_s's rules of depth from "
                         "4,096 (a rung bought, a hold, or a park): an estimate where the bundle was read by the first "
                         "reading, which the second reads at its largest size two chains read and with eight fates")}


TOP_SCORES = 25


def scores_in(laws: list[dict]) -> dict | None:
    found = [(law, law["score"]["score"]) for law in laws
             if law["score"] and isinstance(law["score"].get("score"), dict)]
    if not found:
        return None
    above = [(law, score) for law, score in found if int(score.get("score") or 0) > 0]
    top = sorted(above, key=lambda ls: (-int(ls[1]["score"]), -int(ls[1].get("to_n") or 0), ls[0]["law"]))
    return {"laws": len(found), "above_zero": len(above),
            "by": dict(Counter(str(score.get("by")) for _law, score in above).most_common()),
            "values": {str(value): count for value, count in sorted(
                Counter(int(score["score"]) for _law, score in above).items(), reverse=True)},
            "top": [{"law": law["law"][:12], "campaign": law["campaign"], "score": score["score"], "by": score.get("by"),
                     "chain": score.get("chain"), "to_n": score.get("to_n"), "top_n": score.get("top_n"),
                     "temperature": "zero" if law["zero_temperature"] else law["beta"], "terms": law["ops"]}
                    for law, score in top[:TOP_SCORES]]}


def start_dimension(lattice: str, sizes) -> int | None:
    from graph_scale_dynamics.observability import starts_reading as F
    from graph_scale_dynamics.observability import space_score as S
    family = {name: fam for fam, (name, _d) in F.LATTICES.items()}.get(lattice)
    if family is None:
        return None
    by_n = {str(n): ref for n, ref in (F.table_references().get(family) or {}).items()}
    if not by_n:
        return None
    rungs = [{"n": int(n), "start": (by_n.get(str(n)) or {}).get("start") or {}} for n in sorted(set(sizes))
             if str(n) in by_n]
    return S.chain_dimension(rungs, "start") if rungs else None


def _named(law: dict, label: str, five: dict) -> dict:
    beta = law.get("beta")
    hot = "zero" if law["zero_temperature"] else (float(f"{float(beta):.3g}") if isinstance(beta, (int, float))
                                                    else "finite")
    score = law.get("score") or {}
    chains = score.get("chains") or {}
    reads = {(score.get("given") or "given") if name == "given" else name: (chain or {}).get("d")
             for name, chain in sorted(chains.items())}
    fates = {name: [fate, None if kept is None else round(float(kept), 3)]
             for name, (fate, kept) in sorted((five.get("fates") or {}).items())}
    start_reads = {}
    for name, (fate, _kept) in fates.items():
        if fate == "holds":
            sizes = [int(row[0]) for row in (chains.get(name) or {}).get("rungs") or [] if row and row[1] is not None]
            start_reads[name] = start_dimension(name, sizes)
    another = sorted(name for name, start in start_reads.items()
                     if start is not None and reads.get(name) is not None and abs(reads[name] - start) >= APART_DIMENSIONS)
    return {"law": law["law"][:12], "campaign": law.get("campaign_id"), "class": label, "at_n": five.get("at_n"),
            "temperature": hot, "terms": law["ops"], "lattices": fates, "reads": reads,
            "start_reads": start_reads, "holds_another_dimension": another}


def _lattice_cell(entry, reads=None, start=None) -> str:
    fate, kept = (list(entry or []) + [None, None])[:2]
    marked = start is not None and reads is not None and abs(reads - start) >= APART_DIMENSIONS
    return (f"{fate or 'not read'}" + ("" if kept is None else f" {kept:.2f}")
            + ("" if reads is None else f", reads {reads}")
            + ("" if start is None or start == reads else f" (start {start})") + (" *" if marked else ""))


def render(result: dict) -> str:
    lines = [f"# The starts in {result['bundle']}", "",
             f"Read by {', '.join(result['reading']) or 'no reading of the starts'}; {result['laws_read']:,} of the "
             f"{result['laws_scored']:,} laws that reached 1,024 read ({CONTRACT}). Recorded, never judged.", "",
             "| class | laws |", "|---|---|"]
    lines += [f"| {label} | {count:,} |" for label, count in result["classes"].items()]
    lines += ["", f"Not read at their largest size: {result['largest_size_by_the_chain_from_empty_alone']:,} laws with "
                  "a size below it that two chains read (the chain from empty crossed the cap before the others ran), "
                  f"and {result['no_size_read_by_two_chains']:,} with no size from 1,024 that two chains read.",
              f"Laws read with a lattice of no fate: {result['laws_with_a_lattice_of_no_fate']:,}, by the law's latest "
              "decision: " + ", ".join(f"{rule} {count:,}" for rule, count in
                                       result["laws_with_a_lattice_of_no_fate_by_decision"].items()) + ".", "",
              "| lattice | " + " | ".join(sorted({f for c in result["fates"].values() for f in c})) + " |"]
    names = sorted({f for c in result["fates"].values() for f in c})
    lines.append("|---|" + "---|" * len(names))
    lines += [f"| {lattice} | " + " | ".join(str(counts.get(f, 0)) for f in names) + " |"
              for lattice, counts in result["fates"].items()]
    held = result["held"]
    lines += ["", f"Lattices that held: {held['lattices']} in {held['laws']} laws; kept " +
              ", ".join(f"{band}: {count}" for band, count in sorted(held["kept"].items())) +
              f"; laws with one kept 0.8 or more: {held['laws_kept_from_0_8']}; kept exactly all of it: "
              f"{len(held['kept_all_of_it'])} (" + "; ".join(
                  f"`{h['law']}` {h['lattice']}, {'zero' if h['zero_temperature'] else 'finite'} temperature, "
                  f"{'+'.join(h['terms'])}" for h in held["kept_all_of_it"]) + ")."]
    if held.get("laws_named"):
        given = L.lattices_given(h["lattices"] for h in held["laws_named"])
        lines += ["", f"Every law with a lattice that held, by name: {len(held['laws_named'])}, "
                      f"{held['at_a_finite_temperature']} of them at a finite temperature and {held['from_16384']} "
                      "read from 16,384 (each lattice's fate, the share of its start's reach it kept and the dimension "
                      "its chain reads, its exact start's beside it where they differ; the dimension the chains from "
                      "empty and from the random start read under theirs):", "",
                  "| law | campaign | class | read at | temperature | terms | empty, random | "
                  + " | ".join(given) + " |",
                  "|---|---|---|---|---|---|---|" + "---|" * len(given)]
        lines += [f"| `{h['law']}` | {h['campaign']} | {h['class']} | {h['at_n'] or '-'} | "
                  f"{'zero' if h['temperature'] == 'zero' else 'beta ' + str(h['temperature'])} | "
                  f"{'+'.join(h['terms'])} | {(h.get('reads') or {}).get('empty', '-')}, "
                  f"{(h.get('reads') or {}).get('random', '-')} | "
                  + " | ".join(_lattice_cell(h["lattices"].get(name), (h.get("reads") or {}).get(name),
                                             (h.get("start_reads") or {}).get(name)) for name in given)
                  + " |" for h in held["laws_named"]]
        lines += ["", "\\* holds while its chain reads two dimensions or more away from its exact start at the same "
                      "sizes (the space score's dimension, floored at 2, on the committed references; a difference of "
                      "one is inside the starts' own coarseness): a fate reads a lattice's reach and degree, not its "
                      f"shape, so its shape did not hold. {held.get('holding_another_dimension', 0)} such laws."]
    if result["a_start_reaching_a_shape"]:
        lines += ["", "Read as a start reaching a shape (one_space, grows, converts), with the kept share of the lattice "
                      "that held: " + "; ".join(f"`{r['law']}` {r['class']}, " + ", ".join(
                          f"{name} {kept}" for name, kept in r["held"].items()) for r in result["a_start_reaching_a_shape"])
                  + "."]
    lines += ["", "What the starts' depth rule would make of the laws whose latest decision is one of d_s's rules "
                  "of depth from 4,096:", "", "| at a restart | laws |", "|---|---|"]
    lines += [f"| {key} | {count:,} |" for key, count in result["at_a_restart"].items()]
    lines += ["", result["reading_note"] + ".", "", "Each class against the law's latest decision:", ""]
    for label, rules in result["against_the_latest_decision"].items():
        lines.append(f"* {label}: " + ", ".join(f"{rule} {count:,}" for rule, count in rules.items()))
    lines += _render_decided(result.get("decided") or {}) + _render_against(result.get("against"))
    lines += _render_scores(result.get("scores"))
    return "\n".join(lines) + "\n"


def _render_scores(found: dict | None) -> list[str]:
    lines = ["", "## The scores (608)", ""]
    if not found:
        return lines + ["None in this bundle: its report 28 carries no law's score."]
    lines.append(f"{found['above_zero']:,} of {found['laws']:,} laws score above zero; by who built the geometry: "
                 f"{_counts(found['by'])}; by score: {_counts(found['values'])}.")
    if found["top"]:
        lines += ["", "| law | campaign | score | built by | chain | to N | measured to N | temperature | terms |",
                  "|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| `{t['law']}` | {t['campaign']} | {t['score']} | {t['by']} | {t['chain']} | {t['to_n']} | "
                  f"{t['top_n']} | {t['temperature'] if t['temperature'] == 'zero' else 'beta ' + str(t['temperature'])} | "
                  f"{'+'.join(t['terms'])} |" for t in found["top"]]
    return lines


def _counts(counts: dict) -> str:
    return ", ".join(f"{key} {value:,}" for key, value in counts.items()) or "none"


def _render_decided(decided: dict) -> list[str]:
    lines = ["", "## What the starts decided", ""]
    switch = decided.get("at_the_switch") or {}
    if not (decided.get("decisions") or switch.get("laws") or decided.get("not_taken")
            or decided.get("failed_in_report_28")):
        return lines + ["None in this bundle: no decision of theirs is in its campaigns' record."]
    lines += [f"{decided['decisions']:,} decisions for {decided['laws']:,} laws in {decided.get('campaigns', 0)} "
              f"campaigns, {decided['first_utc']} to {decided['last_utc']}, counted from {decided['from']}. Parked "
              f"where d_s's rule would have climbed or held: {len(decided['parked_where_d_s_climbed']):,} laws; "
              f"climbed where it would have parked: {len(decided['climbed_where_d_s_parked']):,}. Where they had the "
              f"word and did not take it: {_counts(decided['not_taken'])}.", "",
              "| the starts | d_s's rule would have | decisions | laws |", "|---|---|---|---|"]
    for failed in decided.get("failed_in_report_28") or []:
        lines.insert(3, f"Campaign {failed['campaign']}'s count failed in report 28 ({failed['error']}) and is counted "
                        "from report 10's rules instead.")
    lines += [f"| {row['starts_reading']} | {row['d_s']} | {row['decisions']:,} | {row['laws']:,} |"
              for row in decided["against_d_s"]]
    lines += ["", f"Decided again at the switch: {switch.get('laws', 0):,} laws, {len(switch.get('unparked') or []):,} "
                  f"of them parked before and not now, {len(switch.get('parked') or []):,} parked now and not before.",
              "", "| was | now | laws |", "|---|---|---|"]
    lines += [f"| {row['was']} | {row['now']} | {row['laws']:,} |" for row in switch.get("kinds") or []]
    lines += ["", "Each park's let-through, by what its laws read a size later (a shape there is what the park would "
                  "have cost):", ""]
    for park, row in (decided.get("let_through") or {}).items():
        shapes = "; a shape: " + ", ".join(f"`{law[:12]}`" for law in row["a_shape"]) if row["a_shape"] else ""
        lines.append(f"* {park}: {row['laws']:,} laws; {_counts(row['a_size_later'])}{shapes}")
    return lines


def _render_against(found: dict | None) -> list[str]:
    if not found:
        return []
    lines = ["", f"## Against {found.get('earlier') or 'the earlier reading'}, law by law", "",
             f"{found['laws_in_both']:,} laws in both ({found['only_in_the_first']:,} only in the earlier, "
             f"{found['only_in_the_second']:,} only in this one); {found['read_at_a_common_size']:,} read by both at a "
             f"common size, {found['same_class_at_the_same_size']:,} of them in the same class there; apart then and "
             f"alike now {found['apart_then_alike_now']:,}, alike then and apart now "
             f"{found['alike_then_apart_now']:,}.",
             "", "At the largest size both read a law, the earlier class and this bundle's:", ""]
    lines += [f"* {label}: {_counts(counts)}" for label, counts in found["at_the_same_size"].items()]
    lines += ["", "Then, the earlier class, and now, this bundle's at its own size:", ""]
    lines += [f"* {label}: {_counts(counts)}" for label, counts in found["then_and_now"].items()]
    if found.get("the_estimate"):
        lines += ["", "The earlier bundle's estimate of a restart, law by law, against each law's decision now:", ""]
        lines += [f"* {key}: {_counts(counts)}" for key, counts in found["the_estimate"].items()]
    return lines


def laws_text(payload: dict) -> str:
    head = {key: value for key, value in payload.items() if key != "laws"}
    lines = [json.dumps(head, sort_keys=True)[:-1] + ', "laws": {']
    laws = sorted(payload.get("laws") or {})
    lines += [f"{json.dumps(law)}: {json.dumps(payload['laws'][law], sort_keys=True)}" + ("," if i < len(laws) - 1
                                                                                          else "")
              for i, law in enumerate(laws)]
    return "\n".join(lines) + "\n}}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/starts_bundle.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", help="where to write the reading")
    parser.add_argument("--md", help="where to write it as a page")
    parser.add_argument("--laws", help="where to write every law's classes, law by law, for a later bundle's --against")
    parser.add_argument("--against", help="an earlier bundle's laws, as --laws wrote them, to read this one against")
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd_starts_") as scratch:
        root = unpacked(Path(args.bundle), Path(scratch))
        data = L.study(root)
        result = read(root, data)
        laws = law_classes(data["parts"]) if (args.laws or args.against) else None
    if args.against:
        earlier = json.loads(Path(args.against).read_text(encoding="utf-8"))
        result["against"] = dict(against(earlier.get("laws") or {}, laws), earlier=earlier.get("bundle"),
                                 earlier_reading=earlier.get("reading"))
    if args.laws:
        Path(args.laws).write_text(laws_text({"contract": LAWS_CONTRACT, "bundle": result["bundle"],
                                              "reading": result["reading"], "laws": laws}), encoding="utf-8")
    page = render(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(page, encoding="utf-8")
    print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
