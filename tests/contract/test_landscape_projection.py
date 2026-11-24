from __future__ import annotations

import re
from pathlib import Path

from graph_scale_dynamics.research.stability_score import score_law
from graph_scale_dynamics.services.api.landscape_worker import stability_fields

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "graph_scale_dynamics" / "resources" / "ui" / "app.js"

_STABILITY_READ = re.compile(r"\.\s*(stability_[a-z0-9_]+)")


def _app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _projected_fields() -> set[str]:
    scored = score_law(
        {"d_s": [2.10, 2.44, 2.55], "d_V": [], "d_B": [], "d_w": []},
        {"d_s": [None, None, None], "d_V": [], "d_B": [], "d_w": []},
        floors={"d_s": 0.308, "d_V": 0.030, "d_B": 0.125, "d_w": 0.077},
        sizes=[64, 256, 1024],
    )
    return set(stability_fields(dict(scored, score_status="partial")))


def test_the_dashboard_reads_no_stability_field_the_projection_omits():
    read = set(_STABILITY_READ.findall(_app_js()))
    read.discard("stability_approach")
    missing = sorted(read - _projected_fields())
    assert not missing, (
        "app.js reads landscape-row fields that landscape_worker.stability_fields "
        "does not emit: " + ", ".join(missing)
        + ". A read of an absent field is valid JavaScript that yields undefined, "
        "so the panel renders empty and looks like it is working. Emit the field "
        "in the projection, or stop reading it."
    )


def test_the_projection_emits_nothing_the_dashboard_ignores():
    consumed_elsewhere = {"stability_valid_rungs"}
    read = set(_STABILITY_READ.findall(_app_js())) | consumed_elsewhere
    unused = sorted(_projected_fields() - read)
    assert not unused, (
        "landscape rows carry fields no dashboard page reads: " + ", ".join(unused)
        + ". Name the consumer in `consumed_elsewhere` or drop the field."
    )
