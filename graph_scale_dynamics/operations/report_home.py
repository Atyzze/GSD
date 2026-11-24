from __future__ import annotations

import re
from pathlib import Path

POINTER_NAME = "current_campaign"
ROOT_PREFIX = "live_campaign_"
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def base_of(report_root: Path) -> Path:
    root = Path(report_root)
    return root.parent if root.name.startswith(ROOT_PREFIX) else root


def root_for(base: Path, campaign_id: str) -> Path:
    return Path(base) / f"{ROOT_PREFIX}{campaign_id}"


def read_pointer(base: Path) -> str | None:
    try:
        value = (Path(base) / POINTER_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if _ID.match(value) else None


def write_pointer(base: Path, campaign_id: str) -> None:
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{POINTER_NAME}.tmp"
    tmp.write_text(str(campaign_id), encoding="utf-8")
    tmp.replace(base / POINTER_NAME)


def current_root(launch_root: Path | None) -> Path | None:
    if launch_root is None:
        return None
    base = base_of(launch_root)
    pointed = read_pointer(base)
    return root_for(base, pointed) if pointed else Path(launch_root)
