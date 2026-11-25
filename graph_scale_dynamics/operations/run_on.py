from __future__ import annotations

import hashlib
import json

from graph_scale_dynamics.decisions import by_word
from graph_scale_dynamics.domain.model import RUNNING_CANDIDATE_STATES

LISTED = "study_{study}_run_on.json"
NOTHING = "nothing read"


def listed(study: str, tree=None) -> dict:
    from graph_scale_dynamics.resources import committed
    path = committed.path(LISTED.format(study=str(study)), tree)
    if not path.is_file():
        raise ValueError(f"this tree commits no run-on list for study {study} ({committed.relative(path.name)})")
    raw = path.read_bytes()
    found = json.loads(raw)
    return dict(found, path=committed.relative(path.name), sha256=hashlib.sha256(raw).hexdigest())


def chosen(found: dict) -> list[dict]:
    return [row for row in found.get("laws") or [] if row.get("class") != NOTHING]


def name(repo, study: str, *, tree=None) -> dict:
    found = listed(study, tree)
    gate, at_n = str(found["gate"]), int(found["at_n"])
    made: dict[str, dict[str, dict]] = {}
    missing = []
    for row in chosen(found):
        present = repo.conn.execute("SELECT 1 FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
                                    (str(row["campaign"]), str(row["law"]))).fetchone()
        if present is None:
            missing.append(f"{row['campaign']}:{str(row['law'])[:12]}")
            continue
        made.setdefault(str(row["campaign"]), {})[str(row["law"])] = {
            "gate": gate, "at_n": at_n, "list": found["path"], "class": row.get("class")}
    if not made:
        raise ValueError(f"none of the {len(chosen(found))} laws of {found['path']} is in this folder")
    repo.set_flag(by_word.FLAG, json.dumps(by_word.flag(found, made), sort_keys=True, separators=(",", ":")))
    return {"named": sum(len(laws) for laws in made.values()), "missing": missing, "list": found["path"],
            "gate": gate, "at_n": at_n}


def lists(studies: list[dict], tree=None) -> list[dict]:
    out = []
    for entry in studies or []:
        try:
            found = listed(str(entry["study"]), tree)
        except (ValueError, OSError):
            continue
        out.append({"study": str(entry["study"]), "list": found["path"], "gate": found["gate"],
                    "at_n": int(found["at_n"]), "held": int(found.get("held") or 0), "run_on": len(chosen(found)),
                    "classes": found.get("classes"), "bundle": (found.get("bundle") or {}).get("name")})
    return out


def clear(repo) -> dict:
    repo.set_flag(by_word.FLAG, "")
    return {"named": 0}


def reading(repo) -> dict | None:
    value = by_word.flag_value(repo.get_flag(by_word.FLAG, ""))
    if not value:
        return None
    laws = []
    for campaign, named in sorted((value.get("laws") or {}).items()):
        for law, entry in sorted(named.items()):
            row = repo.conn.execute(
                "SELECT c.state, d.action, d.rule, d.at_n, d.next_n FROM campaign_candidates c "
                "LEFT JOIN engine_decisions_latest d ON d.campaign_id=c.campaign_id AND d.candidate_id=c.candidate_id "
                "WHERE c.campaign_id=? AND c.candidate_id=?", (str(campaign), str(law))).fetchone()
            ran = repo.conn.execute(
                "SELECT 1 FROM engine_decisions WHERE campaign_id=? AND candidate_id=? AND rule=? LIMIT 1",
                (str(campaign), str(law), by_word.RULE)).fetchone() is not None
            state = None if row is None else str(row["state"])
            where = ("waiting" if not ran else "running on" if state in RUNNING_CANDIDATE_STATES else "settled")
            laws.append({"campaign": str(campaign), "law": str(law), "class": entry.get("class"), "stage": where,
                         "state": state, "rule": None if row is None else row["rule"],
                         "at_n": None if row is None or row["at_n"] is None else int(row["at_n"])})
    stages: dict[str, int] = {}
    for row in laws:
        stages[row["stage"]] = stages.get(row["stage"], 0) + 1
    return {"list": value.get("list"), "sha256": value.get("sha256"), "laws": laws, "stages": stages}


__all__ = ["chosen", "clear", "listed", "lists", "name", "reading"]
