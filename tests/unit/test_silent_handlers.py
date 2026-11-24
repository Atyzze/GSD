import re
from pathlib import Path
from graph_scale_dynamics.services.api import host as api_host
from tests.support import split_sources

ROOT = Path(__file__).resolve().parents[2]
LOUD = ("log", "print", "raise", "emit", "error", "warn", "incidents.record", "_note_swallowed")

SILENT_HANDLERS_ALLOWED = 0


def silent_handlers(source: str) -> list[int]:
    lines = source.splitlines()
    silent = []
    for i, line in enumerate(lines):
        m = re.match(r"(\s*)except Exception(\s+as\s+\w+)?\s*:", line)
        if not m:
            continue
        indent = len(m.group(1))
        body = []
        for k in range(i + 1, len(lines)):
            if not lines[k].strip():
                continue
            if len(lines[k]) - len(lines[k].lstrip()) <= indent:
                break
            body.append(lines[k])
        if not any(any(word in b for word in LOUD) for b in body):
            silent.append(i + 1)
    return silent


def test_the_api_module_has_no_more_silent_handlers_than_allowed():
    silent = [f"{module.name}:{line}" for module in split_sources.API_MODULES
              for line in silent_handlers(module.read_text())]
    assert len(silent) <= SILENT_HANDLERS_ALLOWED, (
        f"silent `except Exception` handlers at lines {silent}; wire them through "
        "_note_swallowed rather than raising SILENT_HANDLERS_ALLOWED")


def test_the_note_names_the_site_and_the_frame(capsys):
    from graph_scale_dynamics.services.api import main as api
    api_host._SWALLOWED_LOG.clear()
    try:
        raise ValueError("boom")
    except ValueError as exc:
        api._note_swallowed("test_site", exc)
        api._note_swallowed("test_site", exc)
    err = capsys.readouterr().err
    assert err.count("[api] test_site: swallowed ValueError: boom") == 1
    assert "test_silent_handlers.py:" in err, "the frame is the point"
