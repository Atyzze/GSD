from __future__ import annotations

import json

from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.observability import selection_ladder
from graph_scale_dynamics.services.api.answer_cache import ANSWERS

STUDY = "study"
FOCUS_KINDS = ("focus", "seed")


def study_campaigns(repo) -> list[str]:
    from graph_scale_dynamics.operations.study import LAW_BUDGET_PREFIX
    budgets = {str(r["key"])[len(LAW_BUDGET_PREFIX):] for r in repo.conn.execute(
        "SELECT key FROM control WHERE key LIKE ? AND value<>''", (LAW_BUDGET_PREFIX + "%",)).fetchall()}
    designs = {}
    for row in repo.conn.execute("SELECT campaign_id,status,spec_json FROM campaigns").fetchall():
        if str(row["status"] or "") == "archived":
            continue
        try:
            design = (json.loads(row["spec_json"] or "{}") or {}).get("study_design") or {}
        except (TypeError, ValueError):
            design = {}
        designs[str(row["campaign_id"])] = design if isinstance(design, dict) else {}
    found = [cid for cid in designs if cid in budgets]
    studies = {str(designs[cid].get("study")) for cid in found if designs[cid].get("study") is not None}
    found += [cid for cid, design in designs.items()
              if cid not in found and design.get("kind") in FOCUS_KINDS and str(design.get("study")) in studies]
    return sorted(found, key=lambda cid: (not cid.isdigit(), int(cid) if cid.isdigit() else 0, cid))


def answer(repo, campaign: str) -> dict:
    ids = study_campaigns(repo) if str(campaign) == STUDY else [str(campaign)]
    found = selection_ladder.facts(repo, ids)
    return {"contract": selection_ladder.CONTRACT, "campaign": str(campaign), "campaigns": ids,
            "fields": list(selection_ladder.FIELDS), "facts": found, "ladder": selection_ladder.ladder(found)}


def get(handler, db_path: str, parts: list[str]) -> None:
    if len(parts) != 3:
        return handler._json({"error": "use /api/selection-ladder/<campaign id or study>"}, 404)
    try:
        def now():
            with Repo(db_path) as repo:
                return answer(repo, parts[2])
        handler._json(ANSWERS.answer(("selection-ladder", db_path, parts[2]), now))
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def hours(handler, db_path: str, parts: list[str]) -> None:
    from graph_scale_dynamics.observability import study_hours
    if len(parts) != 3:
        return handler._json({"error": "use /api/study-hours/<campaign id or study>"}, 404)
    try:
        def now():
            with Repo(db_path) as repo:
                ids = None if parts[2] == STUDY else [parts[2]]
                return study_hours.hours(repo, ids)
        handler._json(ANSWERS.answer(("study-hours", db_path, parts[2]), now))
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


__all__ = ["STUDY", "answer", "get", "hours", "study_campaigns"]
