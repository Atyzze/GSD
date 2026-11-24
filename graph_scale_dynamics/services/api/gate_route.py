from __future__ import annotations

import json

from graph_scale_dynamics.db.decision_store import EARLY_STAGE_FLAG
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.research.gate_report import folder_status
from graph_scale_dynamics.services.api.answer_cache import ANSWERS

def _status_now(db_path: str, campaign_id: str | None) -> dict:
    with Repo(db_path) as repo:
        return folder_status(repo, campaign_id)


def get(handler, db_path: str, parts: list[str]) -> None:
    campaign_id = parts[2] if len(parts) >= 3 else None
    try:
        handler._json(ANSWERS.answer(("gate", db_path, campaign_id), lambda: _status_now(db_path, campaign_id)))
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def set_early_stage(repo, on: bool) -> dict:
    repo.set_flag(EARLY_STAGE_FLAG, "on" if on else "off")
    repo.emit("gate_early_stage", {"on": bool(on), "utc": utc_now()})
    return folder_status(repo)


def post(handler, db_path: str, parts: list[str], max_bytes: int) -> None:
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except ValueError:
        handler._json({"error": "invalid Content-Length"}, 400)
        return
    if length < 0 or length > max_bytes:
        handler._json({"error": "request body too large"}, 413)
        return
    try:
        body = json.loads(handler.rfile.read(length).decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        handler._json({"error": "invalid JSON"}, 400)
        return
    if len(parts) != 3 or parts[2] != "early_stage":
        handler._json({"error": "use /api/gate/early_stage"}, 404)
        return
    try:
        if not isinstance(body.get("on"), bool):
            handler._json({"error": "send {\"on\": true} or {\"on\": false}"}, 400)
            return
        with Repo(db_path) as repo:
            answer = set_early_stage(repo, body["on"])
        ANSWERS.forget("gate", db_path)
        handler._json(answer)
    except ValueError as exc:
        handler._json({"error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
