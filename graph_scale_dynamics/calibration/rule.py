from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / "graph_scale_dynamics" / "resources" / "calibration" / "table_rule_2.json"
HOLDS = ROOT / "graph_scale_dynamics" / "resources" / "calibration" / "table_holds.json"
RULE_CONTRACT = "gsd-table-rule-2"
HOLDS_CONTRACT = "gsd-table-holds-1"
PROBES = ("d_s", "d_V", "d_B", "d_w")


def _json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rule() -> dict:
    document = _json(RULE)
    if document.get("contract") != RULE_CONTRACT:
        raise ValueError(f"{RULE.name} is not a {RULE_CONTRACT}")
    return document


def derive(document: dict | None = None) -> dict:
    document = document or rule()
    criterion_path, judged_path = (ROOT / document["rests_on"][key] for key in ("criterion", "judged"))
    criterion, judged = _json(criterion_path), _json(judged_path)
    if not judged.get("passes") or judged.get("criterion") != criterion.get("contract"):
        raise ValueError(f"{judged_path.name} is not a passing reading of {criterion_path.name}")
    return {"contract": HOLDS_CONTRACT,
            "made_by": "python3 tools/table_rule.py --write, from the rule and the two files it rests on; never by hand",
            "rule_sha256": _sha256(RULE), "criterion_sha256": _sha256(criterion_path),
            "judged_sha256": _sha256(judged_path),
            "a_refusal_is_required_from_nodes": int(criterion["verdict_held_from_nodes"]),
            "without_a_dimension": sorted(criterion["without_a_dimension"]),
            "with_a_dimension": {family: judged["holds"][family] for family in sorted(criterion["with_a_dimension"])}}


def holds() -> dict:
    document = _json(HOLDS)
    if document.get("contract") != HOLDS_CONTRACT:
        raise ValueError(f"{HOLDS.name} is not a {HOLDS_CONTRACT}")
    return document


def band_at(held: dict | None, n: int) -> float | None:
    chosen = None
    for nodes, within in (held or {}).get("bands") or ():
        if int(n) >= int(nodes):
            chosen = float(within)
    return chosen


def write() -> dict:
    document = derive()
    HOLDS.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return document
