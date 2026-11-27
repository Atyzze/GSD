from __future__ import annotations

import re
from pathlib import Path

import pytest

from graph_scale_dynamics.services.web.main import SPA_SHELL_PATHS

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "graph_scale_dynamics" / "resources" / "ui" / "app.js"


def _client_page_paths() -> dict[str, str]:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"^const pagePath=\{(.*?)\};?$", source, re.MULTILINE)
    assert match, "pagePath is not declared in app.js in the expected form"
    return dict(re.findall(r"(\w+):'([^']+)'", match.group(1)))


def test_the_client_declares_the_pages_this_test_is_about():
    pages = _client_page_paths()
    assert list(pages) == ["home", "map", "top", "campaigns", "explorer", "reports", "calibration", "system"]


@pytest.mark.parametrize("page,path", sorted(_client_page_paths().items()))
def test_every_client_page_is_served_by_the_shell(page: str, path: str):
    assert path in SPA_SHELL_PATHS, (
        f"app.js can navigate to {page} at {path!r} and the web server has no "
        f"route for it, so a real GET -- from a candidate page, a bookmark or a "
        f"refresh -- answers 404 instead of the application")


def test_the_shell_serves_nothing_the_client_cannot_reach():
    known = set(_client_page_paths().values()) | {
        "/index.html",
        "/home",
    }
    stale = sorted(SPA_SHELL_PATHS - known)
    assert not stale, (
        f"the shell serves these and no client page claims them: {stale}")
