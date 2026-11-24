from __future__ import annotations

import os
from pathlib import Path


class InjectedFault(RuntimeError):
    pass


def _selected(point: str) -> bool:
    configured = {
        item.strip() for item in os.environ.get("GSD_FAULT_POINTS", "").split(",")
        if item.strip()
    }
    return point in configured or "*" in configured


def _claim_once(point: str) -> bool:
    root = os.environ.get("GSD_FAULT_ONCE_DIR")
    if not root:
        return True
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / point.replace("/", "_").replace(".", "_")
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    else:
        os.close(fd)
        return True


def hit(point: str) -> None:
    if os.environ.get("GSD_ENABLE_FAULT_INJECTION") != "1":
        return
    if not _selected(point) or not _claim_once(point):
        return
    action = os.environ.get("GSD_FAULT_ACTION", "exception").strip().lower()
    if action == "exit":
        os._exit(int(os.environ.get("GSD_FAULT_EXIT_CODE", "86")))
    if action.startswith("sleep:"):
        import time
        time.sleep(max(0.0, float(action.split(":", 1)[1])))
        return
    raise InjectedFault(f"injected fault at {point}")
