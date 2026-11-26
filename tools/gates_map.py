#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_JSON = ROOT / "docs" / "diagrams" / "gates_and_streams.json"
OUT_SVG = ROOT / "docs" / "diagrams" / "gates_and_streams.svg"
PACKAGE = ROOT / "graph_scale_dynamics"
ENGINE_SOURCES = ("decisions/engine.py", "decisions/decider.py", "decisions/starts_rule.py",
                  "decisions/depth.py", "decisions/nothing_read.py", "decisions/known_result.py",
                  "decisions/steady_chain.py", "decisions/cut.py", "decisions/memory_ceiling.py")
ACTIONS = {"RUN_NEXT": "run_next", "HOLD": "hold", "STOP": "stop", "DONE": "done"}
EVIDENCE_TABLES = ("campaigns", "proposal_draws", "campaign_candidates", "jobs", "attempts", "artifacts",
                   "analysis_queue", "analysis_attempts", "measurements", "rung_summaries", "rung_diagnostics",
                   "rung_operational_terminals", "four_rung_phenotypes", "candidate_state_history",
                   "engine_decisions")
STAGES = ("operational", "final verdict", "settling", "deep rungs", "structure")
COLOURS = {"operational": "#6b6b6b", "final verdict": "#b3261e", "settling": "#7b3fa0", "deep rungs": "#c26a1b",
           "structure": "#1f5fa8", "draw": "#555555", "run_next": "#3a7d44", "audit": "#2a8c8c",
           "hold": "#d99a1e", "stop": "#b3261e", "done": "#2a6f97", "table": "#44546a"}
FONT = "DejaVu Sans, Verdana, sans-serif"
DRAW_WORDS = {"no_terms": "a law with no terms", "over_budget": "over the complexity budget",
              "duplicate_term": "one term twice", "no_sparse_phase": "nothing keeps it sparse",
              "unbounded_below": "falls without bound", "duplicate_law": "a law the campaign holds",
              "duplicate_identity": "the same law, written apart",
              "coefficient_bound": "a coefficient past the DSL's bound", "set_aside": "set aside for another stratum"}


def _functions(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def draw_refusals() -> list[dict]:
    functions = _functions(PACKAGE / "services" / "proposer" / "blind.py")
    codes = [node.value.value for node in ast.walk(functions["validity_problem"])
             if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value]
    for node in ast.walk(functions["blind_batch"]):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "note" and node.args:
            for constant in ast.walk(node.args[0]):
                if isinstance(constant, ast.Constant) and isinstance(constant.value, str) \
                        and constant.value != "admitted" and constant.value not in codes:
                    codes.append(constant.value)
    return [{"code": code, "what": DRAW_WORDS.get(code, "not in the search space")} for code in codes]


def _constants(tree: ast.Module) -> dict:
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            pairs = (zip(target.elts, node.value.elts, strict=True) if isinstance(target, ast.Tuple)
                     and isinstance(node.value, ast.Tuple) else [(target, node.value)])
            for name, value in pairs:
                if isinstance(name, ast.Name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out[name.id] = value.value
    return out


def written() -> list[dict]:
    found: dict[tuple, dict] = {}
    for relative in ENGINE_SOURCES:
        tree = ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))
        named = _constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in ("make", "Decision"):
                continue
            action = node.args[0] if name == "make" and len(node.args) >= 2 else None
            rule = node.args[1] if name == "make" and len(node.args) >= 2 else None
            keywords = {k.arg: k.value for k in node.keywords}
            action, rule = keywords.get("action", action), keywords.get("rule", rule)
            action = ACTIONS.get(getattr(action, "id", "") or getattr(action, "attr", ""), None)
            value = (rule.value if isinstance(rule, ast.Constant) and isinstance(rule.value, str)
                     else named.get(rule.id) if isinstance(rule, ast.Name) else None)
            if action and value:
                found.setdefault((action, value), {"action": action, "rule": value, "where": relative,
                                                   "line": node.lineno})
    from graph_scale_dynamics.decisions import engine as E
    from graph_scale_dynamics.decisions import starts_rule as FS
    from graph_scale_dynamics.decisions import gates as G
    for name in [n for n, _ in E.FINAL_VERDICTS] + sorted(r for r in E.GATE_RULES if r in G.BY_NAME):
        found.setdefault(("stop", name), {"action": "stop", "rule": name, "where": "decisions/engine.py",
                                          "line": None})
    for name in FS.PARKS:
        found.setdefault(("stop", name), {"action": "stop", "rule": name, "where": "decisions/starts_rule.py",
                                          "line": None})
    order = {"run_next": 0, "hold": 1, "stop": 2, "done": 3}
    return sorted(found.values(), key=lambda row: (order[row["action"]], row["where"], row["line"] or 10 ** 6))


def evidence() -> list[dict]:
    schema = (PACKAGE / "resources" / "schema" / "schema.sql").read_text(encoding="utf-8")
    edges = []
    for table, cols, ref, refcols in re.findall(
            r"ALTER TABLE ONLY (\w+)\s+ADD CONSTRAINT \w+ FOREIGN KEY \(([^)]*)\) REFERENCES (\w+)\(([^)]*)\)", schema):
        if table in EVIDENCE_TABLES and ref in EVIDENCE_TABLES and table not in (ref, "campaigns"):
            edges.append({"table": table, "refers_to": ref, "by": cols.replace(" ", "")})
    keyed = {e["table"] for e in edges}
    for table in EVIDENCE_TABLES:
        if table not in keyed and table not in ("campaigns",):
            match = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", schema, re.S)
            if match and "candidate_id" in match.group(1) and "campaign_id" in match.group(1):
                edges.append({"table": table, "refers_to": "campaign_candidates",
                              "by": "campaign_id,candidate_id (no foreign key)"})
    return sorted(edges, key=lambda e: (EVIDENCE_TABLES.index(e["refers_to"]), EVIDENCE_TABLES.index(e["table"])))


def model() -> dict:
    from graph_scale_dynamics.decisions import engine as E
    from graph_scale_dynamics.decisions import gates as G
    from graph_scale_dynamics.research import gate_tree as T
    rules = written()
    gated = {row["rule"] for row in rules if row["action"] in ("stop", "hold")}
    can = {(row["action"], row["rule"]) for row in rules}
    declared = {(stream.action, stream.rule) for stream in G.STREAMS}
    return {
        "contract": "gsd-gates-map-1",
        "drawn_by": "tools/gates_map.py",
        "draw": draw_refusals(),
        "gates": [{"name": g.name, "stage": g.stage, "reads": g.reads, "salted": g.salted, "why_not": g.why_not}
                  for g in G.GATES],
        "salt": {"share": E.Policy().audit_fraction, "buys": "one rung past where the gate stops a law (537)",
                 "own_share_since_554": {"testing_below_16384": T.SALT_WHILE_TESTING[T.CHEAP],
                                         "testing_from_16384": T.SALT_WHILE_TESTING[T.DEEP],
                                         "confirmed": T.SALT_CONFIRMED}},
        "streams": [{"action": s.action, "rule": s.rule, "means": s.means, "audit": s.audit,
                     "gate": s.rule in G.BY_NAME} for s in G.STREAMS],
        "stops_that_are_not_gates": sorted(gated - set(G.BY_NAME)),
        "written_but_not_declared": sorted(f"{a} {r}" for a, r in can - declared),
        "declared_but_not_written": sorted(f"{a} {r}" for a, r in declared - can),
        "lanes": {str(k): v for k, v in sorted(E.LANE_ORDER.items())},
        "evidence": evidence(),
    }


def _text(x, y, body, *, size=12, weight="normal", fill="#1d1d1f", anchor="start") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{escape(str(body))}</text>')


def _box(x, y, w, h, stroke, fill="#ffffff") -> str:
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" ry="6" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>')


def _arrow(x1, y1, x2, y2, colour="#666666") -> str:
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    left = (x2 - 9 * math.cos(angle - 0.4), y2 - 9 * math.sin(angle - 0.4))
    right = (x2 - 9 * math.cos(angle + 0.4), y2 - 9 * math.sin(angle + 0.4))
    return (f'<path d="M{x1:.1f} {y1:.1f} L{x2:.1f} {y2:.1f}" fill="none" stroke="{colour}" stroke-width="1.2"/>'
            f'<path d="M{x2:.1f} {y2:.1f} L{left[0]:.1f} {left[1]:.1f} L{right[0]:.1f} {right[1]:.1f} Z" '
            f'fill="{colour}" stroke="none"/>')


def _wrap(text: str, width: int) -> list[str]:
    lines, line = [], ""
    for word in str(text).split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


def svg(m: dict) -> str:
    width, left = 1600, 30
    out, y = [], 40
    out.append(_text(left, y, "Gates and streams: what a law meets from its draw to its last rung", size=20,
                     weight="bold"))
    out.append(_text(left, y + 22, "Drawn from the code by tools/gates_map.py; checked current by "
                     "tests/unit/test_gates_map_is_current.py. The same content is in gates_and_streams.json.",
                     size=12, fill="#555555"))
    y += 60
    out.append(_text(left, y, "1  Drawn: the proposer refuses a law, in this order", size=15, weight="bold"))
    y += 14
    x = left
    for row in m["draw"]:
        w = max(110, 8 * len(row["code"]) + 20, 6 * len(row["what"]) + 20)
        out.append(_box(x, y, w, 44, COLOURS["draw"]))
        out.append(_text(x + w / 2, y + 18, row["code"], size=12, weight="bold", anchor="middle"))
        out.append(_text(x + w / 2, y + 34, row["what"], size=10, fill="#555555", anchor="middle"))
        out.append(_arrow(x + w, y + 22, x + w + 16, y + 22))
        x += w + 18
    out.append(_box(x, y, 150, 44, COLOURS["run_next"], "#eef6ef"))
    out.append(_text(x + 75, y + 18, "admitted", size=12, weight="bold", anchor="middle"))
    out.append(_text(x + 75, y + 34, "a law of the campaign", size=10, fill="#555555", anchor="middle"))
    y += 80

    share, own = f"{m['salt']['share']:.0%}", m["salt"].get("own_share_since_554") or {}
    since = (f", or from 554 its own: {own['testing_below_16384']:.0%}/{own['testing_from_16384']:.0%} testing, "
             f"{own['confirmed']:.0%} confirmed" if own else "")
    out.append(_text(left, y, f"2  At each rung, the gates in the order a law meets them (a gate that lets a share through lets {share} "
                     f"of what it stops go one rung on{since})", size=15, weight="bold"))
    y += 14
    column = (width - 2 * left - 4 * 12) / len(STAGES)
    tallest = y
    for i, stage in enumerate(STAGES):
        x = left + i * (column + 12)
        out.append(_text(x, y + 14, stage, size=13, weight="bold", fill=COLOURS[stage]))
        cy = y + 24
        for gate in [g for g in m["gates"] if g["stage"] == stage]:
            lines = _wrap(gate["reads"], 44)[:3]
            salt = [f"lets {share} through, one rung on"] if gate["salted"] else _wrap("lets none through: " + gate["why_not"], 44)[:3]
            h = 26 + 14 * (len(lines) + len(salt))
            out.append(_box(x, cy, column, h, COLOURS[stage]))
            out.append(_text(x + 10, cy + 18, gate["name"], size=12, weight="bold"))
            for j, line in enumerate(lines):
                out.append(_text(x + 10, cy + 34 + 14 * j, line, size=10))
            for j, line in enumerate(salt):
                out.append(_text(x + 10, cy + 34 + 14 * (len(lines) + j), line, size=10,
                                 fill="#3a7d44" if gate["salted"] else "#6b6b6b"))
            cy += h + 10
        tallest = max(tallest, cy)
    y = tallest + 30

    out.append(_text(left, y, "3  The streams a decision sends a law down (decisions/gates.STREAMS: every action and "
                     "rule the engine writes)", size=15, weight="bold"))
    y += 14
    groups = (("run_next: on its own reading", [s for s in m["streams"] if s["action"] == "run_next" and not s["audit"]],
               COLOURS["run_next"]),
              ("run_next: audit traffic, its own lane", [s for s in m["streams"] if s["action"] == "run_next" and s["audit"]],
               COLOURS["audit"]),
              ("hold: waits at its rung", [s for s in m["streams"] if s["action"] == "hold"], COLOURS["hold"]),
              ("stop: a gate stopped it", [s for s in m["streams"] if s["action"] == "stop"], COLOURS["stop"]),
              ("done: its ladder is complete", [s for s in m["streams"] if s["action"] == "done"], COLOURS["done"]))
    column = (width - 2 * left - 4 * 12) / len(groups)
    tallest = y
    for i, (title, rows, colour) in enumerate(groups):
        x = left + i * (column + 12)
        out.append(_text(x, y + 14, title, size=12, weight="bold", fill=colour))
        cy = y + 24
        for row in rows:
            lines = _wrap(("the gate's: " if row["gate"] else "") + row["means"], 48)[:3]
            h = 24 + 13 * len(lines)
            out.append(_box(x, cy, column, h, colour))
            out.append(_text(x + 10, cy + 17, row["rule"], size=11, weight="bold"))
            for j, line in enumerate(lines):
                out.append(_text(x + 10, cy + 31 + 13 * j, line, size=9, fill="#555555"))
            cy += h + 6
        tallest = max(tallest, cy)
    for key, words in (("stops_that_are_not_gates", "stopped under a rule that is not a named gate: "),
                       ("written_but_not_declared", "the engine can write a stream not declared: "),
                       ("declared_but_not_written", "declared and written nowhere: ")):
        if m[key]:
            out.append(_text(left, tallest + 6, words + ", ".join(m[key]), size=12, fill=COLOURS["stop"]))
            tallest += 20
    y = tallest + 30

    out.append(_text(left, y, "4  Where a law's evidence is kept: each table and the keys that tie it to another",
                     size=15, weight="bold"))
    y += 20
    depth = {"campaigns": 0}
    for _ in range(len(EVIDENCE_TABLES)):
        for edge in m["evidence"]:
            if edge["refers_to"] in depth:
                depth[edge["table"]] = max(depth.get(edge["table"], 0), depth[edge["refers_to"]] + 1)
    layers: dict[int, list[str]] = {}
    for table in EVIDENCE_TABLES:
        if table in depth:
            layers.setdefault(depth[table], []).append(table)
    box_w, box_h, gap_x, gap_y = 210, 30, 44, 14
    place = {}
    for d, tables in sorted(layers.items()):
        for k, table in enumerate(tables):
            place[table] = (left + d * (box_w + gap_x), y + k * (box_h + gap_y))
    through = {e["table"] for e in m["evidence"] if e["refers_to"] == "campaign_candidates"}
    for edge in m["evidence"]:
        if edge["refers_to"] == "campaigns" and edge["table"] in through:
            continue
        (x1, y1), (x2, y2) = place[edge["table"]], place[edge["refers_to"]]
        out.append(_arrow(x1, y1 + box_h / 2, x2 + box_w, y2 + box_h / 2, "#8a96a8"))
    for table, (x, ty) in place.items():
        out.append(_box(x, ty, box_w, box_h, COLOURS["table"], "#f4f6f9"))
        out.append(_text(x + box_w / 2, ty + 19, table, size=11, weight="bold", anchor="middle"))
    y = max(ty for _, ty in place.values()) + box_h + 30
    out.append(_text(left, y, "An arrow runs from a table to the one its key refers to (a table's campaign, when "
                     "its law's key already gives it, is not drawn again); a key with no foreign key behind it, and "
                     "every key, is in the JSON.", size=10, fill="#555555"))
    height = y + 24
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{width}" height="{height:.0f}" viewBox="0 0 {width} {height:.0f}">\n'
            f'<title>Gates and streams (tools/gates_map.py)</title>\n'
            f'<rect x="0" y="0" width="{width}" height="{height:.0f}" fill="#ffffff" stroke="none"/>\n')
    return head + "\n".join(out) + "\n</svg>\n"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    current = model()
    text_json = json.dumps(current, indent=1) + "\n"
    text_svg = svg(current)
    if "--check" in args:
        stale = [p.name for p, t in ((OUT_JSON, text_json), (OUT_SVG, text_svg))
                 if not p.is_file() or p.read_text(encoding="utf-8") != t]
        print("the map is current" if not stale else f"stale: {', '.join(stale)}; run python3 tools/gates_map.py")
        return 1 if stale else 0
    OUT_JSON.write_text(text_json, encoding="utf-8")
    OUT_SVG.write_text(text_svg, encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_SVG.relative_to(ROOT)}: {len(current['draw'])} refusals, "
          f"{len(current['gates'])} gates, {len(current['streams'])} streams, {len(current['evidence'])} keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
