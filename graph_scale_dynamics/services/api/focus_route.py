from __future__ import annotations

import json

from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.operations import focus

PAGE_CONTRACT = "gsd-map-page-1"


def answer(repo) -> dict:
    from graph_scale_dynamics.operations import run_on
    from graph_scale_dynamics.scheduling import work_groups
    return {"contract": PAGE_CONTRACT, "focus": focus.reading(repo), "studies": focus.studies(repo),
            "workload": work_groups.reading(repo), "defaults": focus.settings_of(focus.plan()),
            "run_on": run_on.reading(repo), "run_on_lists": run_on.lists(focus.studies(repo))}


def get(handler, db_path: str, parts: list[str]) -> None:
    if parts != ["api", "focus"]:
        return handler._json({"error": "use /api/focus"}, 404)
    try:
        with Repo(db_path) as repo:
            handler._json(answer(repo))
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def _body(handler, max_bytes: int) -> dict | None:
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except ValueError:
        handler._json({"error": "invalid Content-Length"}, 400)
        return None
    if length < 0 or length > max_bytes:
        handler._json({"error": "request body too large"}, 413)
        return None
    try:
        body = json.loads(handler.rfile.read(length).decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        handler._json({"error": "invalid JSON"}, 400)
        return None
    if not isinstance(body, dict):
        handler._json({"error": "send a JSON object"}, 400)
        return None
    return body


def post(handler, db_path: str, parts: list[str], max_bytes: int) -> None:
    if parts != ["api", "focus"]:
        return handler._json({"error": "use POST /api/focus"}, 404)
    body = _body(handler, max_bytes)
    if body is None:
        return None
    try:
        with Repo(db_path) as repo:
            done = focus.act(repo, body)
            handler._json(dict(done, **answer(repo)))
    except ValueError as exc:
        handler._json({"error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
