from __future__ import annotations

import html
import json
import os
from pathlib import Path


def browser_launcher(var: Path, admin_url: str) -> str:
    path = var / "run" / "dashboard-open.html"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        link = html.escape(admin_url, quote=True)
        handle.write(f"<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=\"0;url={link}\">"
                     f"<script>location.replace({json.dumps(admin_url)})</script><a href=\"{link}\">the dashboard</a>\n")
    return path.resolve().as_uri()
